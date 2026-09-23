#!/usr/bin/env python3
"""LoRA SFT on multi-turn tool-use traces (training/build_sft.py output), or
on the older prompt→completion pairs (select_traces.py, the overfit smoke).

  # the real thing: OProver-8B (dense Qwen3, ~16GB bf16; fits one 48GB L40S)
  python3 train_sft.py --data data/astra-student/v1 --out checkpoints/astra-student-v1

  # the original overfit smoke test
  python3 train_sft.py --data data/sft_promptfinal.jsonl --model Qwen/Qwen2.5-Coder-1.5B-Instruct \
      --chat-template none --epochs 40 --out checkpoints/overfit10

Qwen3.6-35B-A3B is NOT supported yet: it is a vision-language model
(Qwen3_5MoeForConditionalGeneration, text weights under
model.language_model), 30 of its 40 layers are linear attention
(linear_attn.in_proj_qkv / in_proj_z / out_proj, not q/k/v/o_proj), and its
routed experts are fused 3D params PEFT can't target by name. Loading,
masked_lm_loss's backbone access, and LoRA targets all need a load test on
a GPU node first.

Loss is on assistant tokens only: visible text, tool calls, and the
end-of-turn token. System/user/tool turns (the prompt, and every tool
result: compile errors, score JSON) are context with label -100. Training on
tool output would teach the model to hallucinate scores.

Masking is by character offset into ONE rendering of the whole
conversation: each assistant turn spans from the end of
render(messages[:i], add_generation_prompt=True) to the end of
render(messages[:i+1]). Both must be exact prefixes of the full rendering,
checked per example, so a chat template that renders history differently
(e.g. strips old turns' <think> blocks) fails loudly instead of silently
masking the wrong tokens. Thinking is off (enable_thinking=False), matching
how the student is served.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Callable

LEGACY_SYSTEM_PROMPT = (
    "You are an expert Lean 4 proof engineer. Rewrite the given theorem's "
    "proof to be as short and cheap to elaborate as possible while "
    "preserving the exact statement. Reply with only the final declaration."
)


def assistant_spans(render: Callable[..., str], messages: list[dict[str, Any]]) -> tuple[str, list[tuple[int, int]]]:
    """(full text, [(start, end) char spans to train on]). `render(msgs, gen)` renders a chat."""
    full = render(messages, False)
    spans = []
    for i, m in enumerate(messages):
        if m["role"] != "assistant":
            continue
        head = render(messages[:i], True)
        upto = render(messages[: i + 1], False)
        if not (full.startswith(head) and full.startswith(upto) and len(head) <= len(upto)):
            raise ValueError(
                f"chat template is not prefix-stable at message {i} — loss masking would be "
                "wrong. Inspect the tokenizer's chat_template (history rendering, think blocks); "
                "for stock Qwen3 / OProver pass --chat-template templates/qwen3_stable_think.jinja."
            )
        spans.append((len(head), len(upto)))
    return full, spans


def load_examples(data: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]] | None]:
    """(train, val, tools). A mixture directory, or a legacy prompt/completion jsonl."""
    def read(p: Path) -> list[dict[str, Any]]:
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.is_file() else []

    if data.is_dir():
        manifest = json.loads((data / "manifest.json").read_text())
        return read(data / "train.jsonl"), read(data / "val.jsonl"), manifest["tools"]
    rows = read(data)
    legacy = [{"messages": [
        {"role": "system", "content": LEGACY_SYSTEM_PROMPT},
        {"role": "user", "content": r["prompt"]},
        {"role": "assistant", "content": r["completion"]},
    ]} for r in rows]
    return legacy, [], None


def encode(tokenizer, example: dict[str, Any], tools, max_len: int) -> dict[str, list[int]] | None:
    def render(msgs, gen):
        return tokenizer.apply_chat_template(
            msgs, tools=tools, tokenize=False, add_generation_prompt=gen, enable_thinking=False,
        )

    full, spans = assistant_spans(render, example["messages"])
    enc = tokenizer(full, add_special_tokens=False, return_offsets_mapping=True)
    ids = enc["input_ids"]
    if len(ids) > max_len:
        print(f"  SKIP {example.get('name', '?')}@{example.get('episode', '?')}: {len(ids)} tokens > --max-len {max_len}")
        return None
    labels = [-100] * len(ids)
    for k, (start, end) in enumerate(enc["offset_mapping"]):
        if any(s <= start and end <= e and end > start for s, e in spans):
            labels[k] = ids[k]
    return {"input_ids": ids, "labels": labels, "attention_mask": [1] * len(ids)}


def masked_lm_loss(model, inputs, chunk: int = 2048):
    """Cross-entropy on trained positions only, never materializing full logits.

    A 20k-token trace x 152k vocab is ~12GB of fp32 logits (twice that in the
    loss): it OOMed a 24GB card with a 0.6B model. Only ~15% of positions are
    trained, so run the backbone for hidden states and apply lm_head to just
    those rows, in chunks.
    """
    import torch
    import torch.nn.functional as F

    base = model.get_base_model() if hasattr(model, "get_base_model") else model
    hidden = base.model(input_ids=inputs["input_ids"],
                        attention_mask=inputs.get("attention_mask")).last_hidden_state
    targets = inputs["labels"][:, 1:]
    keep = targets != -100
    h, y = hidden[:, :-1][keep], targets[keep]
    total = h.new_zeros((), dtype=torch.float32)
    for i in range(0, len(y), chunk):
        logits = base.lm_head(h[i:i + chunk]).float()
        total = total + F.cross_entropy(logits, y[i:i + chunk], reduction="sum")
    return total / max(len(y), 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="mixture dir (data/<mixture>/<version>) or legacy .jsonl")
    ap.add_argument("--model", default="m-a-p/OProver-8B")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--max-len", type=int, default=40960, help="OProver-8B's context; longer episodes are skipped (and counted)")
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lora-r", type=int, default=32)
    ap.add_argument("--target-modules", nargs="*",
                    default=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
                    help="all attention + MLP projections (right for dense Qwen3 / OProver). "
                         "On an MoE base these names also hit every expert — restrict them.")
    ap.add_argument("--load-in-4bit", action="store_true", help="QLoRA (needs bitsandbytes)")
    ap.add_argument("--chat-template", default=str(Path(__file__).resolve().parent / "templates" / "qwen3_stable_think.jinja"),
                    help="chat template (.jinja) to train with; saved with the adapter so serving "
                         "uses the same one. Default is the prefix-stable Qwen3 template that stock "
                         "Qwen3 / OProver need. Pass 'none' to keep the tokenizer's own "
                         "(e.g. Qwen2.5, or Qwen3.6 whose template is already prefix-stable).")
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
                              DataCollatorForSeq2Seq, Trainer, TrainingArguments)

    train_rows, val_rows, tools = load_examples(Path(args.data))
    print(f"loaded {len(train_rows)} train / {len(val_rows)} val examples from {args.data}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    if args.chat_template and args.chat_template != "none":
        tokenizer.chat_template = Path(args.chat_template).read_text()

    def dataset(rows):
        encoded = [e for e in (encode(tokenizer, r, tools, args.max_len) for r in rows) if e]
        if len(encoded) < len(rows):
            print(f"  WARNING: {len(rows) - len(encoded)}/{len(rows)} examples skipped as too long")
        n_tok = sum(len(e["input_ids"]) for e in encoded)
        n_lab = sum(sum(1 for x in e["labels"] if x != -100) for e in encoded)
        print(f"  {len(encoded)} examples, {n_tok} tokens, {n_lab} trained ({n_lab / max(n_tok, 1):.1%})")
        return Dataset.from_list(encoded) if encoded else None

    train_ds, val_ds = dataset(train_rows), dataset(val_rows)
    if train_ds is None:
        raise SystemExit("no training examples fit --max-len")

    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_compute_dtype=torch.bfloat16) if args.load_in_4bit else None
    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=torch.bfloat16, device_map="auto", quantization_config=quant,
    )
    if quant is not None:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(
        r=args.lora_r, lora_alpha=2 * args.lora_r, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM", target_modules=args.target_modules,
    ))
    model.print_trainable_parameters()
    # Frozen-base activations aren't checkpointed by default; without this a
    # 1.5B model already OOMed a 24GB card at ~2.9K tokens. LoRA freezes the
    # input embeddings, so checkpointing needs enable_input_require_grads.
    model.config.use_cache = False
    model.enable_input_require_grads()
    model.gradient_checkpointing_enable()

    class MaskedLossTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            loss = masked_lm_loss(model, inputs)
            return (loss, {}) if return_outputs else loss

    trainer = MaskedLossTrainer(
        model=model,
        args=TrainingArguments(
            output_dir=args.out,
            num_train_epochs=args.epochs,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=args.grad_accum,
            learning_rate=args.lr,
            lr_scheduler_type="cosine",
            # warmup_ratio was removed in transformers 5; steps work on every version.
            warmup_steps=max(1, int(0.05 * math.ceil(len(train_ds) / args.grad_accum) * args.epochs)),
            logging_steps=5,
            eval_strategy="epoch" if val_ds is not None else "no",
            save_strategy="epoch",
            save_total_limit=2,
            bf16=True,
            report_to=[],
            remove_unused_columns=False,
            prediction_loss_only=True,
        ),
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100),
    )
    trainer.train()
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    (Path(args.out) / "sft_data.json").write_text(json.dumps({"data": str(args.data), "model": args.model,
                                                                         "chat_template": args.chat_template}))
    print(f"saved adapter to {args.out}")


if __name__ == "__main__":
    main()
