---
title: Rho — Reference Implementation Detail
source: Internal Axiom reconstruction, brought into this repo 2026-08-15
status: Reference material. Not our plan.
---

# Rho — Reference Implementation Detail

**This is not the plan.** Our own plan is architectural and
stands on its own. This document is the configuration-level detail behind Rho, kept
because it is the only copy we have and because the numbers are useful as anchors
for what a pipeline at that scale actually costs. Read it when you are sizing a run
or resolving a specific "what did they set this to" question — not to understand the
approach.

Covers data → SFT → RL → eval. The agent harness (trace generation / RL environment) is out of scope; it appears only as the producer of SFT traces and the RL rollout environment.

Reconstructed from the `axiom` monorepo. The production SFT config (§3.3) and the gold RL config (§4.2) are reproduced verbatim; the dataset mixtures, datagen plan, and hyperparameter schemas are given field by field. Infrastructure and artifacts required are listed in [§8](#8-what-you-must-have-access-to).

---

## 0. Overview

Rho is **not pretrained from scratch**. It is a fine-tune of a Qwen MoE base:

```
Qwen/Qwen3.6-35B-A3B  ──SFT (full FT, Megatron-SWIFT)──▶  checkpoint-1150  ──RL (GRPO/CISPO, snorlax)──▶  policy
```

- **Base model (both stages):** `Qwen/Qwen3.6-35B-A3B` (35B total, ~3B active MoE).
- **Objective:** supervised fine-tune on agentic proving traces, then sequence-level RL with a **binary Lean-verification reward** (AXLE).
- **Reward signal in RL:** proof verifies → 1.0, else 0.0. No shaped reward in the production run.

### Two SFT stacks — do not confuse them
| Stack | Path | Use | Base for prod? |
|---|---|---|---|
| **Megatron-SWIFT (production)** | `prover/megatron_sft/rho/` | Full fine-tune of the 35B; produced `checkpoint-1150` | **Yes** |
| Tinker / LoRA (legacy, small) | `rho/packages/training/rho_training/sft/` | Small-model / quick LoRA runs | No — see Appendix |

**Replicate the Megatron-SWIFT path.** The Tinker defaults (4B, LoRA r16, lr 1e-4) are a different, smaller pipeline.

> ⚠️ Read **§6 (Caveats)** before launching anything — there are real divergences between the "gold" config and the checkpoint that was actually shipped/benchmarked (LR, Lean version, tool protocol, KV-scale eval).

### 0.1 SFT runbook — the whole path, in order

Each step is expanded later in the document; this is the sequence, so you never have to reconstruct it.

1. **Confirm access** to the accounts, buckets, and volumes in [§8](#8-what-you-must-have-access-to). Set `WANDB_API_KEY` as an env var — a `wandb login` session is not enough for Modal submits.
2. **Land traces** in `s3://axiom-rho-data/raw/traces/{source}/{date}/` from the harness. This guide does not cover producing them.
3. **Index them** so the build can see them, and beat the 48h freshness gate:
   ```bash
   rho-data index --sources <your_source> synthetic --days None
   ```
4. **Write a mixture spec** — presets, budgeting, ordering, and the dedup/split keys are in §2.2; decontamination in §2.3. Start from the production spec, given field by field in §2.4 (`sft_v1_opus_synthetic_proofmix.yaml`, 638M completion tokens).
5. **Dry-run, then build** the dataset. The build refuses to overwrite an existing `{name}/{version}`, and writes `manifest.json` last as the commit marker:
   ```bash
   rho-data build --spec <your_spec>.yaml --plan-only
   rho-data build --spec <your_spec>.yaml
   ```
6. **Train.** The one-shot launcher encodes onto the `prover-sft-data` volume, injects the encoded paths, and submits to Modal in one call:
   ```bash
   uv run --project prover python -m prover.megatron_sft.rho.launch \
     --dataset <name>/<version> \
     --config <your_config>.yml
   ```
   Use the production config in §3.3 verbatim as your starting point. The thing that makes this Rho and not vanilla SFT is **provenance masking** (§3.2) — read that section before changing `--train-tokens`.
7. **Collect the checkpoint** from `/prover-sft-megatron-checkpoints/<output_dir>/checkpoint-<step>`. That path is what RL consumes as `model.base_checkpoint`.

RL is a separate stage with its own pool build (§2.6), policy-specific calibration (§2.7), and launch (§4.1). You do not need it to reproduce SFT.

---

## 1. Environment & backends

| Concern | Value |
|---|---|
| SFT trainer | **Megatron-SWIFT (ms-swift)**, Modal-hosted. `image_variant: cu13_rho`, `gpu_type: H200`, `world_size: 32`, `memory_gb: 1024` |
| RL trainer | **snorlax** = Modal Megatron trainer + co-located SGLang samplers, driven via `tweak`'s tinker-compatible client (`forward_backward_async`). `tinker` client pinned **0.19.0** (gateway rejects mismatches) |
| Serving (eval) | vLLM in-container from the checkpoint volume; standing deploys are FP8 E4M3 KV-cache B200 apps |
| Experiment tracking | **W&B**. SFT → `rho-sft`; RL → `rho-rl`; eval detail → `rho-evals`. `WANDB_API_KEY` env var required for Modal submits (not just `wandb login`) |
| Lean verifier | **AXLE** (hosted HTTP or Modal in-process). Prod RL/eval pin **lean-4.27.0**; repo default is `lean-4.32.0` (see §6) |
| Retrieval (RL tool) | Atlas semantic search; RL default `embedding_backend: modal`, version `v4_31_0` |
| Tracing (optional) | Langfuse (`langfuse.axiommath.ai`, VPC-internal, over Tailscale); off by default |

### S3 layout (`rho_data/pipeline/config.py`)
```
s3://axiom-rho-data/raw/traces                          # ingested harness rollouts
s3://axiom-rho-data/raw/index                           # daily trace index (TraceMeta)
s3://axiom-rho-data/datasets/sft/{name}/{version}/      # built SFT parquet
s3://axiom-rho-data/datasets/rl/{name}/{version}/       # built RL task pools
s3://axiom-rho-data/datasets/rl/calibrations/{name}/{version}   # calibrated RL pools
s3://axiom-rho-data/problems/fineleancorpus/v3          # FineLeanCorpus v3 splits
s3://axiom-rho-training/runs/sft                        # Tinker-path artifacts (legacy)
```

### Modal volumes / secrets
- **SFT:** ckpt volume `prover-sft-megatron-checkpoints`; HF cache `prover-sft-hf-cache-generic`; encoded-data volume `prover-sft-data` (mounted `/data`).
- **RL:** volumes `prover-sft-hf-cache-generic`, `prover-sft-megatron-checkpoints`, `rho-rl-snorlax`; driver artifacts on `rho-rl-colocated`.
- **RL secrets:** `aws`, `axle-secret`, `tailscale-oauth`, and `wandb-secret-<user>` (or `wandb-secret`). Image build uses `github-chao` (override `RHO_GITHUB_SECRET`). Default Modal env `rho`; Tailscale secret read from `main` (`RHO_TAILSCALE_ENV` overrides).
- **RL is co-located only:** driver + snorlax in one Modal app `rho-rl-<run-id>`; single rank-0 loopback gateway, no public ingress except a CPU dashboard function.

---

## 2. Data pipeline

### 2.1 Trace flow (SFT source data)
```
harness run → ingest Lambda → s3://.../raw/traces/{source}/{date}/rollout-*.jsonl
            → indexer Lambda (daily EventBridge) → raw/index/{source}/{date}.jsonl
            → rho-data build → datasets/sft/{name}/{version}/
```
- **Index-freshness gate:** build refuses if a source's `last_run.json` is missing or older than `max_index_age_hours` (default **48h**).
- **Hard-blocked sources** (never trainable without `allow_non_training_sources`, research only): `eval`, `adhoc`, `playground`, `playground_feedback`.

### 2.2 Build the SFT dataset
```bash
rho-data index --sources rho_sft_v1_run1b synthetic --days None   # backfill the index
rho-data build --spec rho/specs/sft/<spec>.yaml --plan-only        # dry-run the plan
rho-data build --spec rho/specs/sft/<spec>.yaml                    # build + write to S3
rho-data datasets                                                   # summarize built datasets
```

**Build knobs (`BuildConfig`):** `sources=("datagen",)`, `status=("completed",)`, `val_fraction=0.05`, `shard_size=10000` rows/parquet, `seed=42`, `dedup=true`, `order={by: random}`, `max_workers=32`, `overwrite=false` (refuses an existing `{name}/{version}`).

**Presets (`PRESETS`):**
| Preset | verification_results | Psi tool profiles |
|---|---|---|
| `proof` | `(proved,)` | excluded |
| `disproof` | `(disproved,)` | excluded |
| `psi_solved` | `(proved,)` | only |
| `psi_accepted` | `(proved, disproved)` | only |
| `psi_clean` | `(proved,)` | only, `psi_clean=True` |

**Selection & budgeting:** each mixture component = a filter (preset or explicit `filter:`, optionally narrowed by `models:` / `datasets:` / `tags:` / `tool_profiles:`) + a `budget` (absolute int, `all`, or `N%` of the pool's `total_tokens`).
- Pools ordered deterministically by `sha256(f"{seed}:{run_id}")`; `_take_budget` takes the prefix whose cumulative **completion tokens** reach the budget (the crossing trace is included → **budgets nest**: a larger budget is a strict superset).
- Identical filters are memoized to one shared pool; a single streaming pass reads each selected body once and routes it to every dataset that selected it.
- **Dedup key:** `sha256(messages + "\x00" + json(train_kinds))`.
- **Train/val split key:** the **statement** (all solutions to one problem stay on the same side).

**Row schema written (`_row`):** `messages`, `train_kinds` (JSON), `dataset`, `run_id`, `source`, `day`, `window_index`, `n_windows`, `model`, `source_dataset`, `variant_hash`, `runner_batch_id`, `problem_id`, `statement_text_key`, `status`, `trace_format_version`, `task_schema`, `prompt_hash`, `trace_surface_hash`, `harness_protocol_version`. A `manifest.json` is written **last** as the commit marker (per-component traces/tokens/filter, source seen/kept counts, decontamination report, provenance).

**Row ordering (`order.by`):** `random` (default, hash-shuffle interleaving all components) · `natural` (unsorted component blocks) · `difficulty` (trailing int of source-dataset name = FLC level, easy first) · `tokens` (shortest first). Modifiers: `jitter`, `descending`.

### 2.3 SFT eval decontamination
Registry: `rho/datasets/eval_registry.jsonl` (built by the harness `rho-eval-registry` over **miniF2F + ProofNet + PutnamBench + `rho/datasets/eval/`**). A trace is dropped if **any** rule matches:
1. problem provenance names an eval dataset,
2. trace carries **no** theorem hashes at all,
3. AXLE theorem-type hash matches (compared across **all** Lean versions — deliberately over-triggers),
4. exact statement-text match.

Manifest records per-rule counts + registry sha256. `allow_eval_statements=True` disables it (research only).

### 2.4 SFT mixture specs

**Production spec behind the RL base — `sft_v1_opus_synthetic_proofmix.yaml`:**
- sources `[rho_sft_v1_run1b, synthetic]`, `seed 42`, `val_fraction 0.05`.
- dataset `sft_v1_opus_synthetic_proofmix_all_tokens/v1`, two components, both `budget: all`:
  1. `opus_proved_disproved` — `verification_results:[proved,disproved]`, `tool_profiles:[focused_prover]`, `models:["anthropic/claude-opus-4.8"]`
  2. `synthetic_warehouse_proofmix` — `verification_results:[proved]`, `tool_profiles:[focused_prover]`, `tags:[warehouse-psi-difficulty-proofmix-v1]`
- **→ 637,895,569 completion tokens** ("the 638M dataset").

**`sft_v1_mixtures.yaml` (ablation menu):** sources `[rho_sft_v1_run1b, rho_sft_v1_run1b_psi_ext1]`, seed 42. Notable datasets:
- `sft_v1_core_proof_1b_tokens` — proof budget `1e9` (1B proof anchor)
- disproof ladder over 1B total: `_5pct` (95/5), `_10pct` (90/10), `_30pct` (70/30 proof/disproof)
- `sft_v1_actual_solved_all_tokens` — proof `all` + psi_solved `all`
- `sft_v1_all_accepted_tokens` — proof `all` + disproof `all` + psi_accepted `all`
- `sft_v1_psi_clean_overlay_tokens` / `sft_v1_psi_all_accepted_overlay_tokens` — proof `1e9` + psi overlay `all`

**`rho_sft_v2_opus48_plus_opus5_synthetic.yaml` (later v2, NOT the ckpt-1150 base):** sources `[rho_sft_v1_run1b, rho_sft_v2_opus5_lean432_atlasmodal_20260727, synthetic]`, seed **20260729**, val 0.05, `max_workers 64`. Two `all`-budget components: `opus_verified` (`[proved,disproved]`, models `["anthropic/claude-opus-4.8","anthropic/claude-opus-5"]`) + `synthetic_warehouse_proofmix`.

### 2.5 Datagen plan (how the SFT traces were generated) — `rho_sft_v1_run1b_plan.yaml`
`collection_id: rho_sft_v1_run1b`, dataset prefix `FineLeanCorpus_l`, **levels 2–8**, seed 20260618. Per-level routes with `attempt_budget`:
- `ds_focused` (preset `deepseek_v4_flash_focused`)
- `opus_focused` (`opus48_focused`)
- `opus48_psi_edit` — phase psi (`opus48_psi_edit_p8_r3`)
- `ds_opus48_partner` — phase partner (`deepseek_v4_flash_opus48_partner`; fed by failures of `ds_focused`)
- `opus48_gpt55_partner` (`opus48_gpt55_base_16k`; fed by failures of `ds_focused` + `opus_focused`)

Provers: **DeepSeek V4 Flash**, **Claude Opus 4.8**, **GPT-5.5** (partner). Example budgets: L5 `ds_focused` 10018, L6 `opus_focused` 8990, L7 `ds_opus48_partner` 7585.

### 2.6 Build the RL task pool
```bash
rho-data build-rl --spec rho/specs/rl/rl_v1_flc_40k.yaml --plan-only
rho-data build-rl --spec rho/specs/rl/rl_v1_flc_40k.yaml
```
- **Sources may only name `FineLeanCorpusV3_rl_l<N>`** (regex-enforced; train/eval splits are unrepresentable here).
- Output: `tasks.jsonl` (`RlTaskRecord` rows) + `problem_ids.txt` + `original_problem_ids.txt` + `manifest.json`.
- Determinism: `sha256(f"{seed}:{problem_id}")`, count takes a nesting prefix.
- Per-source filters: dedup by `text_key`, optional `require_informal_statement`, `max_statement_chars`.
- Order (`RlOrder`): `natural` · `random` · `level` (jitter/descending) · `gaussian` (moving-mean difficulty curriculum: `mean_start/mean_end/sigma/ramp`).

**Triple decontamination (`_verify`, no bypass; raises `RlContaminationError`)** — every emitted row re-checked against: (1) trace index of traced problems, (2) published v3 splits `("train","eval_small","eval")` by `original_problem_id` + text_key, (3) eval registry. An empty exclusion split is a hard error.

**`rl_v1_flc_40k.yaml`:** seed 42, dataset `rl_v1_flc_40k/v1`, `max_statement_chars: 20000`, `order:{by: level}`. **40,000 problems**: L2 4300 · L3 4100 · L4 7200 · L5 8500 · L6 7900 · L7 6642 · L8 1358.

### 2.7 Calibrate the RL pool (policy-specific; separate from build-rl)
RL trains against a **calibrated** pool — the base policy is probed on each task and only tasks with useful pass-rates are kept.
```bash
uv run --package rho-training rho-train rl-calibrate-file \
  --config .../rl_snorlax_qwen36_35b_calibration_lean432_v1.yaml \
  --calibration.name qwen36_sft1150_lean432_new_pool \
  --calibration.version lean432-pilot-v1 \
  --calibration.problems-per-level 100 --calibration.publish
```
**V2 pool logic:** 4 rollouts first, nonconstant prefix completed to 8. Outputs:
- `train_tasks.jsonl` — full 8-rollout group with **3/8, 4/8, or 5/8** verified (train-eligible band)
- `nonconstant_tasks.jsonl` — **1/8–7/8** verified
- `eval_tasks.jsonl` — deterministic **32-task** holdout (target 16 mixed / 8 all-fail / 8 all-success)
- plus `reserve_tasks.jsonl`, `all_fail_tasks.jsonl`, `results.jsonl`, `rollout_contract.json`, `summary.json`/`manifest.json`

Membership is on **binary `verified` only** (never shaped reward). Published to `s3://axiom-rho-data/datasets/rl/calibrations/{name}/{version}` (+ `tasks.jsonl` alias, `publish.json`). Backend rotation `calibration.backend_rotation_seconds` ≈ 22.5h.

---

## 3. SFT stage (production 35B, Megatron-SWIFT)

### 3.1 Commands
**Encode the committed dataset onto the `prover-sft-data` volume (standalone):**
```bash
uv run --project prover python -m prover.megatron_sft.rho.prepare_encoded_dataset \
  --s3-data-uri s3://axiom-rho-data/datasets/sft/<name>/<version>/ \
  --model Qwen/Qwen3.6-35B-A3B --train-tokens all_assistant --max-length 65536
```
**One-shot launch (encode → inject encoded paths → submit) — the production path:**
```bash
export WANDB_API_KEY=...
uv run --project prover python -m prover.megatron_sft.rho.launch \
  --dataset sft_v1_opus_synthetic_proofmix_all_tokens/v1 \
  --config prover/megatron_sft/configs/rho/sft_v1_data_ablation_128k_lr5e5/opus_synthetic_proofmix_638m_5ep.yml
```
`launch.py` flags: `--train-tokens` (default `all_assistant`), `--enable-thinking/--no-enable-thinking` (default **False**, matches serving), `--echo-loss-weight`, `--force` (re-encode), `--detach`, `--prepare-only`, `--no-checkpoint-eval`, `--local-watcher`. It computes a content-hashed `rho_encoded_<hash>` key, injects `encoded_dataset`/`encoded_val_dataset` (refuses if the config already sets them), stamps a run id, and calls `prover.megatron_sft.submit` in-process.
**Direct submit (skip launch):** `python -m prover.megatron_sft.submit --config-file <resolved>.yml`.

### 3.2 Provenance masking + loss (the crux — this is what makes it Rho and not vanilla SFT)
Loss is masked by **message provenance** (`train_kinds`: `generated` / `summary` / `context`), **not by role**, and baked into `labels` (`-100` at masked positions) at encode time so the ms-swift template never decides which tokens are trained.

- **`--train-tokens`:** `all_assistant` = `{generated, summary}` (default) · `non_compaction` = `{generated}` · `compaction` = `{summary}`. All three mask carried-forward `context` copies (already trained where first generated) and all user/tool/system tokens.
- Within a trained assistant turn, only **response** tokens get loss; the `<|im_start|>assistant\n` header and the empty `<think>\n\n</think>\n\n` prefix (fed, not generated) stay masked. Uses an **overlap** (not containment) test on char offsets so a straddling BPE merge isn't dropped.
- Rendering uses the model's **own HF chat template** (`enable_thinking=False`), byte-identical to what vLLM serves → no train/serve skew. Rows failing turn-structure guards raise `RenderSkew` and are dropped (`dropped_skew`); rows over `max_length` dropped by default (`--on-overflow drop`).
- **Echo loss (optional 2nd term):** `--echo-loss-weight > 0` adds CE over full tool-output content for tools in `echo_tool_names` (default `{check, verify_proof, verify_target, verify_disproof}`) via a per-token `loss_scale` column. `RhoMegatronTrainer.loss_func` optimizes `mean CE(response) + weight * mean CE(echoed)` (two separately normalized terms). **Default weight 0.0 (disabled).**
- **Encoded row:** `input_ids`, `labels`, `loss_scale`, `lengths`. Encode fan-out `ENCODE_CPUS=16`. Output on the `prover-sft-data` volume at `/data/rho_encoded_<hash>/encoded/{train,validation}/`.

### 3.3 Full training config — `opus_synthetic_proofmix_638m_5ep.yml` (verbatim)
```yaml
modal:
  gpu_type: H200
  world_size: 32
  detach: true
  auto_cache_dataset: false
  checkpoint_volume: prover-sft-megatron-checkpoints
  hf_cache_volume: prover-sft-hf-cache-generic
  image_variant: cu13_rho
  max_retries: 3
  memory_gb: 1024
  local_checkpoint_staging: true
  hf_export_sweep: true
  hf_export_memory_gb: 335

rho_checkpoint_eval:
  enabled: false                 # this run disables in-run eval
  spec: fineleancorpus_v3_sft_checkpoint_eval_small.yaml
  poll_seconds: 60
  rho_jobs: 32
  export_backend: hf_safetensors

megatron_sft:
  model: Qwen/Qwen3.6-35B-A3B
  max_length: 131072             # 128k (NB: default elsewhere is 65536 — see §6.3)
  finetune: true
  tuner_type: full               # FULL fine-tune
  freeze_parameters_regex: '\.mlp\.router\.'   # freeze MoE router
  mtp_num_layers: 0
  truncation_strategy: delete
  dataset_shuffle: true
  output_dir: /prover-sft-megatron-checkpoints/qwen36_35b_a3b_sft_v1_opus_synthetic_proofmix_638m_128k_lr5e5_5ep

  report_to: [wandb]
  wandb_project: rho-sft
  wandb_exp_name: qwen36_35b_a3b_sft_v1_opus_synthetic_proofmix_638m_128k_lr5e5_5ep
  logging_steps: 1

  attention_backend: flash
  cross_entropy_loss_fusion: true
  packing: true
  micro_batch_size: 1

  # parallelism (32 GPUs = TP8 × CP2 × EP8)
  tensor_model_parallel_size: 8
  context_parallel_size: 2
  expert_model_parallel_size: 8
  expert_tensor_parallel_size: 1
  sequence_parallel: true

  overlap_grad_reduce: true
  overlap_param_gather: true
  moe_permute_fusion: true
  moe_grouped_gemm: true
  moe_shared_expert_overlap: true
  moe_aux_loss_coeff: 0.0
  moe_expert_capacity_factor: 2
  recompute_granularity: null
  optimizer_cpu_offload: false
  use_precision_aware_optimizer: false

  # schedule
  num_train_epochs: 5
  global_batch_size: 32
  lr: 5.0e-5
  lr_warmup_fraction: 0.05
  min_lr: 5.0e-6

  freeze_llm: false
  freeze_vit: true
  freeze_aligner: true

  add_non_thinking_prefix: true
  loss_scale: last_round+ignore_empty_think

  dataloader_num_workers: 2
  dataset_num_proc: 4

  # checkpointing
  save_steps: 50
  eval_steps: 170
  async_save: true
  use_persistent_ckpt_worker: false
```
ms-swift consumes the encoded data with `truncation_strategy: delete`, `packing: true`, `streaming: false`.

---

## 4. RL stage (snorlax, gold config)

### 4.1 Command
```bash
uv sync --extra snorlax
uv run --package rho-training rho-train rl-file \
  --config packages/training/rho_training/rl/configs/rl_snorlax_qwen36_35b_full_p2000_gold.yaml
```
`rho-train` subcommands: `sft`, `rl-file`, `rl-calibrate-file`, `rl-rebuild-calibration-artifacts`, `rl-dashboard`, `rl-analyze-malformed`. RL is co-located (driver + snorlax in one Modal app). Validate first with `rl_snorlax_memory_smoke.yaml`; cold start ≈ 15 min for 35B.

### 4.2 Gold config — `rl_snorlax_qwen36_35b_full_p2000_gold.yaml` (verbatim)
```yaml
data:
  tasks_jsonl: s3://axiom-rho-data/datasets/rl/calibrations/qwen36_sft1150_fullgroup_v2/full-p2000-qwen3xml-modal-typed-c512-v5-20260715-v1/nonconstant_tasks.jsonl
  require_calibration_contract: true
  sampler:
    mode: adaptive
    weak_calibration_weight: 0.25      # ~70% of draws to strong 3/8–5/8 rows
    cooled_exploration_fraction: 0.10
  # pool = 1969 nonconstant tasks (755 train-eligible) + disjoint 32-task holdout

eval:
  tasks_jsonl: .../eval_tasks.jsonl
  max_tasks: 32
  run_at_start: true
  every_steps: 25
  group_size: 8
  concurrency: 128

model:
  name: Qwen/Qwen3.6-35B-A3B
  base_checkpoint: /prover-sft-megatron-checkpoints/qwen36_35b_a3b_sft_v1_opus_synthetic_proofmix_638m_128k_lr5e5_5ep_20260701T185656Z-7151d78c/checkpoint-1150
  lora_rank: 0                          # full FT
  learning_rate: 1.0e-6                 # NB: shipped p150 came from a 5e-7 sweep — see §6
  lr_schedule: constant

rollout:
  max_turns: null
  max_tokens_per_turn: 16384
  max_context_tokens: 65536
  temperature: 1.0
  group_size: 8
  max_rollout_slot_retries: 2
  batch_size: 256                       # 32 groups × 8 accepted rollouts / optimizer step
  oversampling_factor: 2.5
  queue_size: 80
  max_off_policy_steps: 32
  tool_profile: focused_prover
  tool_protocol: qwen3_xml              # vLLM <function=..><parameter=..> XML, NOT JSON
  verify_timeout_seconds: 300

reward:
  fn: verification
  verified_reward: 1.0
  failed_reward: 0.0

loss:
  algorithm: cispo
  cispo_clip: 2.0

run:
  max_steps: 100
  save_every: 25
  save_final_checkpoint: true
  checkpoint_ttl_days: 10

sandbox:
  kind: memory                          # focused_prover = file ops + hosted AXLE, no backend.run

tool_configs:
  axle:
    backend: modal
    lean_version: lean-4.27.0
    modal:
      app_name: rho-axle-lean-4-27-0
    environment_name: main
    prover_tools_revision: 10b4b3a7ffb8a65199b316511c20b6be609ad16b
    environment_artifact_version: 160ed94
    environment_artifact_sha256: 21cbc2e2a4e977f67b250578dc1af4770a30c3393bf724c1d53d2b714d18c2e3
  atlas_search:
    version: v4_31_0
    allow_version_mismatch: true
    embedding_backend: modal
    caller: rho-rl
    max_concurrency: 64

backend:
  type: snorlax
  num_gpus: 48                          # 16 trainer + 32 samplers
  gpu_type: H200
  server_backend: megatron
  launch_timeout_seconds: 1800
  request_timeout_seconds: 3600
  max_connections: 5120
  cleanup_on_exit: true
  modal_volumes: [prover-sft-hf-cache-generic, prover-sft-megatron-checkpoints, rho-rl-snorlax]
  server_backend_config:
    dp_size: 4
    tp_size: 4
    ep_size: 8
    num_samplers: 32
    sampler_tp_size: 1
    micro_batch_size: 1
    pack_length: 65536
    sampler_mem_fraction_static: 0.8
    sampler_load_format: auto
    sampler_enable_deterministic_inference: false
    enable_weight_sync: true
    pause_generation_mode: abort
    sampler_router_policy: cache_aware
    sgl_router_config: {cache_threshold: 0.3, balance_abs_threshold: 8, balance_rel_threshold: 1.5, disable_retries: true}
    sgl_server_config: {log_level: warning, log_level_http: warning}
    state_volume: rho-rl-snorlax
    state_dir: /rho-rl-snorlax/rho-rl-qwen36-adaptive-v2
    megatron_config:
      params_dtype: bfloat16
      bf16: true
      grad_reduce_in_fp32: true
      use_distributed_optimizer: true
      overlap_param_gather: true
      attention_backend: flash
      cross_entropy_loss_fusion: true
      cross_entropy_fusion_impl: native
      gradient_accumulation_fusion: true
      bias_activation_fusion: true
      bias_dropout_fusion: true
      masked_softmax_fusion: true
      sequence_parallel: true
      moe_token_dispatcher_type: alltoall
      moe_router_dtype: fp32
      moe_permute_fusion: true
      moe_grouped_gemm: true
      moe_shared_expert_overlap: true
      moe_aux_loss_coeff: 0.0
      moe_expert_capacity_factor: null
      recompute_granularity: full
      recompute_method: uniform
      recompute_num_layers: 1
      optimizer: adam
      decoupled_weight_decay: true
      lr: 0.0                            # real LR/grad-clip passed per-step via AdamParams
      clip_grad: 0.0

wandb:
  enabled: true
  project: rho-rl
  name: rho-rl-qwen36-35b-adaptive-v2
```

### 4.3 RL algorithm & defaults (`rho_training/rl/config.py`)
- **Loss (`RlLossConfig`):** `algorithm ∈ {importance_sampling (not implemented), ppo, cispo}`, default **cispo** (truncated importance-sampling REINFORCE; clipped tokens keep a bounded gradient). `cispo_clip=2.0`, `ppo_clip_low=0.8`, `ppo_clip_high=1.28`, `grad_clip_norm=None`, `normalization ∈ {token(default), sequence}`. All losses run backend-native via `forward_backward_async`. `sequence` normalization requires compaction off + exactly one datum/rollout.
- **Advantage / reward:** GRPO-style **group-centered advantage** — every execution + summary token in a rollout gets the same group-centered final advantage ("complete-rollout / Composer-style" credit). `RlRewardConfig`: `normalize_by_std=False`, `normalize_epsilon=1e-6`, `kl_to_sft_model_coeff=None` (optional KL-to-SFT; frozen reference = `model.base_checkpoint`; requires cispo + token norm + a `kl_reference` deployment), `kl_penalty_type=k2`. `RlVerificationRewardConfig`: `verified_reward=1.0`, `failed_reward=0.0`, `completed_reward=0.0`; **all shaping penalties default 0** (`overlong_*`, `repetition_*`, `effort_penalty_*`, `missing_artifact_penalty`, `tool_error_penalty`, `malformed_penalty`).
- **Rollout defaults (`RlRolloutConfig`, before the gold overrides):** `max_turns=10`, `max_tokens_per_turn=2048`, `max_context_tokens=32768`, `temperature=1.0`, `group_size=8`, `batch_size=256`, `oversampling_factor=1.0`, `queue_size=64`, `max_off_policy_steps=2`, `max_group_draws_per_step_multiplier=10`, `max_malformed_retries=1`, `max_sample_transport_retries=5`, `tool_profile=focused_prover`, `tool_protocol=qwen3_native`, `verify_timeout_seconds=300`. `max_inflight_rollouts = round(batch_size × oversampling)`.
- **Off-policy:** `max_off_policy_steps` bounds the gap between the current published policy and the oldest policy in a rollout; stored decode-time logprobs keep importance ratios correct. Weight sync `pause_generation_mode: abort` (cancel in-flight sampling, resample on new weights, keep radix cache warm) vs `in_place`; `retract` unsupported.
- **Sampler modes (`RlSamplerConfig`):** `shuffle` (default) · `sequential` (replay file curriculum) · `adaptive`. Adaptive: `all_fail_cooldown_steps_per_streak=8`, `all_success_cooldown_steps=32`, `cooled_exploration_fraction=0.10`, `weak_calibration_weight=1.0` (gold uses 0.25). Optional `calibration_band_sampling` (Bayesian Beta-posterior: `target_fraction=0.70`, `hard=0.20`, `easy=0.10`, target successes 3–8, `calibration_prior_strength=8.0`, `posterior_half_life_steps=64`, `uniform_exploration_fraction=0.10`).

### 4.4 Hardware / topology
48× H200: 16 trainer (dp4 × tp4 × ep8) + 32 one-GPU TP1 samplers. Measured best admission ≈ 640 request lanes over 32 samplers. Modal's 24h app limit is handled by planned checkpoint rotation (`run.max_relaunches=2`; watchdog `modal deploy ... rho_training.rl.modal_autoresume`). A B200 variant exists (`rl_snorlax_qwen36_35b_full_p2000_b200.yaml`).

---

## 5. Eval

- **SFT in-run checkpoint eval (optional):** the `rho_checkpoint_eval` block in the training YAML spins up a combined Modal app (training + a vLLM server from the checkpoint volume). Logs `eval/<name>` into the training W&B group at the checkpoint step; detail to `rho-evals`. Specs under `rho/specs/eval/fineleancorpus_v3/`. *(Disabled in the 638M config above.)*
- **RL eval (`RlEvalConfig`):** held-out, disjoint from the training pool (errors on overlap unless `allow_training_overlap`), tracks avg verified rate + best-of-K; `mode ∈ {rolling(default), blocking_snapshot}`. Gold: `run_at_start`, `every_steps 25`, `group_size 8`, `concurrency 128`.
- **Benchmark sweep (`rho_q36_fp8_rl_p150_v4270.yaml`):** `mode: eval`, `timeout_seconds: 5400`, `axle.lean_version: lean-4.27.0`, `filter_misformalizations: false`, variant `qwen36_focused`, `temperature 0.7`, `disable_reasoning: true`, `run_policy: verified_or_budget`. **8 pinned benchmarks, 2213 problems:** MiniF2F, ProofNet, PutnamBench, RedBookBenchmark, KenBenchmark, FATE-M, FATE-H, FATE-X. (Other specs: greenbook/redbook/proofnet_qwen36, fate_h_v4270, kenbenchmark_v4270, rest275, joint_p50_clean.)
- Eval decontamination registry built over miniF2F + ProofNet + PutnamBench + `rho/datasets/eval/`.

---

## 6. ⚠️ Caveats & ambiguities — read before replicating

1. **RL learning-rate conflict.** The *gold* config sets `learning_rate: 1.0e-6`, `max_steps: 100`. But the checkpoint actually benchmarked (p150) came from an **lr-sweep at 5e-7** run (`rho-rl-qwen36-35b-adaptive-lr-sweep-5e7-20260729`) that reached step 149. Decide whether you're reproducing the *recommended launch* (gold, 1e-6) or the *shipped weights* (5e-7). Sweep arms: `rl_q36_35b_adapt_lr1e6 / lr5e7 / lr2p5e7 / lr5e7_in_place`.
2. **Lean version divergence.** Production RL/eval pin **lean-4.27.0**; the repo default (`DEFAULT_AXLE_LEAN_VERSION`) and the newer calibration campaign (`rl_snorlax_qwen36_35b_calibration_lean432_v1.yaml`) are **lean-4.32.0**. The 638M SFT base and its RL are a 4.27 artifact; the v2 SFT source name (`..._lean432_...`) is 4.32. Keep the verifier version consistent with the data you train on.
3. **`max_length` 128k vs 65k.** The documented default elsewhere is 65536, and the standalone encode command in §3.1 shows `--max-length 65536`; the production 638M config trains at `max_length: 131072`. `launch.py` reads `max_length` from the config, so the production run encodes at **128k**. RL `pack_length`/`max_context_tokens` are 65536. Pick one and keep encode and train consistent.
4. **Two SFT stacks.** Only the Megatron-SWIFT path produced checkpoint-1150. Do **not** use the Tinker `sft/config.py` defaults (4B/LoRA/lr1e-4) for a 35B replication (see Appendix).
5. **Tool protocol.** RL default is `qwen3_native`, but the shipped checkpoint was trained/served with **`qwen3_xml`** (gold override). Reward parsing depends on this — mismatch it and rollouts parse as malformed.
6. **SFT spec identity.** The RL base used `sft_v1_opus_synthetic_proofmix.yaml` (Opus-4.8 only, seed 42). `rho_sft_v2_opus48_plus_opus5_synthetic.yaml` (adds Opus-5, seed 20260729) is a **later** dataset, not the one behind checkpoint-1150.
7. **p150 eval is not a clean RL isolate.** It was served with FP8 KV scales calibrated from checkpoint-**1292** and compared against a 1292 SFT baseline, so the reported number is RL-delta + (1150→1292 SFT delta).

---

## 7. Exact identifiers

| Item | Value |
|---|---|
| Base model (SFT + RL) | `Qwen/Qwen3.6-35B-A3B` (35B total, ~3B active MoE) |
| SFT dataset | `sft_v1_opus_synthetic_proofmix_all_tokens/v1` — 637,895,569 completion tokens |
| SFT output / RL base ckpt | `/prover-sft-megatron-checkpoints/qwen36_35b_a3b_sft_v1_opus_synthetic_proofmix_638m_128k_lr5e5_5ep_20260701T185656Z-7151d78c/checkpoint-1150` |
| RL calibration artifact | `qwen36_sft1150_fullgroup_v2/full-p2000-qwen3xml-modal-typed-c512-v5-20260715-v1` (1969 nonconstant / 755 train-eligible + 32 holdout) |
| RL benchmarked ckpt (p150) | run `rho-rl-qwen36-35b-adaptive-lr-sweep-5e7-20260729`; served `hf/policy_000150_hf` from `ckpt/step_000149`; W&B `axiommath/rho-rl/runs/zbyfk6ta`; ~15.1h, ~$3.3k |
| RL verifier Lean (gold + eval) | AXLE **lean-4.27.0** (app `rho-axle-lean-4-27-0`) |
| Repo default Lean | `lean-4.32.0` |
| Atlas search version (RL) | `v4_31_0` |
| tinker client pin | 0.19.0 |
| Provers in datagen | Claude Opus 4.8 (+ Opus 5 in v2), DeepSeek V4 Flash, GPT-5.5 (partner) |

---

## 8. What you must have access to

These are credentials, compute, and stored artifacts — not documents to read. Everything textual you need is already in this guide.

| Need | Detail |
|---|---|
| Compute | Modal, env `rho`. SFT: 32× H200, 1024 GB. RL: 48× H200. |
| Base weights | `Qwen/Qwen3.6-35B-A3B` from HF, cached on the `prover-sft-hf-cache-generic` volume. |
| Data bucket | `s3://axiom-rho-data` (layout in §1) plus AWS credentials via the `aws` Modal secret. |
| Modal volumes | `prover-sft-megatron-checkpoints`, `prover-sft-hf-cache-generic`, `prover-sft-data`; RL adds `rho-rl-snorlax`. |
| Secrets | `WANDB_API_KEY` env var, `axle-secret`, `tailscale-oauth`, `github-chao` for the image build. |
| Verifier | AXLE, hosted HTTP or Modal in-process. Pin the Lean version to your data (§6, caveat 2). |
| Trace source | Harness rollouts landing in `raw/traces` — the producer is out of scope here. |
| Eval registry | `rho/datasets/eval_registry.jsonl`, built by the harness command `rho-eval-registry` over miniF2F + ProofNet + PutnamBench. Required for decontamination (§2.3). |

If you need to go past what is written here, the reconstruction came from the `axiom` monorepo (`git@github.com:AxiomMath/axiom.git`) — the production SFT recipe under `prover/megatron_sft/configs/rho/`, the training and RL schemas under `rho/packages/training/`, and the mixtures under `rho/specs/`. All of those are reproduced or summarized above.

---

## 9. How this relates to our plan

Our own approach does not depend on this document. In
summary: we take Rho's three-stage shape (teacher traces → SFT → RL against a Lean
verifier) and three of its architectural ideas — provenance-masked loss,
over-triggering decontamination, and policy-specific pool calibration. We do not
take its reward, which is binary, or its task framing, which is proving from
scratch rather than refactoring. The scale gap is roughly four to five orders of
magnitude, so the configuration values above are anchors for what a full-size run
costs, not targets to match.

---

## Appendix — legacy Tinker/LoRA SFT (NOT the production 35B path)

Recorded so you can recognize these defaults and avoid them, not so you can follow them. Command: `rho-train sft --data.uri ... --model.name Qwen/Qwen3-8B ...`. Defaults:

- `SftDataConfig`: `split=train`, `val_split=validation`, `max_length=32768`, `on_overflow=drop`, `max_drop_rate=0.05`, `shuffle_buffer_size=10000`, `train_tokens=all_assistant`.
- `SftModelConfig`: `name=Qwen/Qwen3-4B-Instruct-2507`, `lora_rank=16`, `learning_rate=1e-4`, `lr_schedule=linear`, `warmup_steps=0`.
- `SftRunConfig`: `artifact_prefix=s3://axiom-rho-training/runs/sft`, `batch_size=8`, `num_epochs=1`, `seed=42`, `save_every=100`, `eval_every=0`, `eval_max_batches=20`, `checkpoint_ttl_days=10`.

Provenance-masking semantics are the same as production (§3.2).
