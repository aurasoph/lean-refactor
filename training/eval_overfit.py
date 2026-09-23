#!/usr/bin/env python3
"""The actual pass/fail signal for the overfit smoke test: does the
LoRA-adapted model reproduce each of the 10 memorized targets when prompted
with its own input? If not, something in the pipeline (data, masking,
chat template, LoRA save/reload) is broken, before we ever get to whether
the recipe generalizes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from train_sft import LEGACY_SYSTEM_PROMPT as SYSTEM_PROMPT


def normalize(s: str) -> str:
    return " ".join(s.split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/sft_promptfinal.jsonl")
    ap.add_argument("--adapter", default="checkpoints/overfit10")
    ap.add_argument("--base-model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    ap.add_argument("--max-new-tokens", type=int, default=1024)
    args = ap.parse_args()

    examples = [json.loads(l) for l in Path(args.data).read_text().splitlines() if l.strip()]

    tokenizer = AutoTokenizer.from_pretrained(args.adapter)
    base = AutoModelForCausalLM.from_pretrained(
        args.base_model, torch_dtype=torch.bfloat16, device_map="auto"
    )
    model = PeftModel.from_pretrained(base, args.adapter)
    model.eval()

    n_exact = 0
    n_close = 0
    for ex in examples:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": ex["prompt"]},
        ]
        # return_dict=True explicitly, rather than relying on return_tensors="pt"
        # alone to imply it — this transformers version's apply_chat_template
        # returns a BatchEncoding either way, and passing that straight to
        # generate() as a positional tensor breaks (`.shape` on a dict-like).
        inputs = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_tensors="pt", return_dict=True,
        ).to(model.device)
        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=args.max_new_tokens, do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        gen = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        target = ex["completion"].strip()
        exact = normalize(gen) == normalize(target)
        close = normalize(target) in normalize(gen) or normalize(gen) in normalize(target)
        n_exact += exact
        n_close += close
        status = "EXACT" if exact else ("CLOSE" if close else "MISS")
        print(f"[{status}] {ex['name']}")
        if not exact:
            print(f"  target ({len(target)} chars): {target[:150]!r}")
            print(f"  got    ({len(gen)} chars): {gen[:150]!r}")

    print(f"\n{n_exact}/{len(examples)} exact match, {n_close}/{len(examples)} close match")


if __name__ == "__main__":
    main()
