# AGENTS.md

Instructions for coding agents working **on** this repo. This file is not for
the teacher models that `arena.py run` launches. They must never see it:
`codex_command()` passes `-c project_doc_max_bytes=0` for that reason. Keep
that flag, and don't add a `CLAUDE.md`, which the `--backend claude` teacher
would load.

## What this is

An entry for the [Lean Refactor Arena](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena):
rewrite a Lean 4 proof to be shorter and cheaper to elaborate, keeping the
statement byte-identical and compiling on every listed toolchain. There are
two tracks:

- **Closed:** closed teachers (Sol `gpt-5.6-sol`, Astra `gpt-6-astra`) run
  through Codex CLI.
- **Open:** a LoRA fine-tune trained on those teachers' traces. The leading
  base is `m-a-p/OProver-8B`, pending a bake-off against Qwen3.6-35B-A3B.
  The budget is about $1k.

See `docs/HANDOFF.md` for machine setup.

## Layout

```
competition/   harness: arena.py (prepare/check/run/usage), verify.py (compile + heartbeats),
               local_score.py, student_tools.py (THE student tool set), collect.py,
               mcp_server/ (tools exposed to Codex), prompts/refactor.md, projects/v4.* (Lake workspaces)
runs/          episode logs; runs/<stamp>-<problem>/{codex.jsonl, tools.jsonl, episode.json}
traces/        legacy harvested rollouts
training/      build_sft.py, train_sft.py, splits.py, templates/, sbatch/ (Klone/Hyak jobs)
mining/        candidate discovery + promotion into competition/benchmark_data_extra.jsonl
docs/          HANDOFF (new-machine setup), STRATEGY, VERSION_MATRIX
```

## The data pipeline

```
nohup python3 competition/collect.py > runs/collect.out 2>&1 &     # days; resumable; --status any time
python3 training/build_sft.py --mixture NAME --version vN [--dry-run] # -> training/data/NAME/vN/
sbatch training/sbatch/train_sft.job  (MIXTURE=data/NAME/vN)          # LoRA on Klone
```

`collect.py` is the whole collection pipeline. It runs Sol on every problem,
then Astra salvage where Sol produced nothing usable, then promotes more
mined problems (`mining/promote_discovered.py` →
`competition/benchmark_data_extra.jsonl` plus reference measurements), then
extra Sol seeds. It stops at `--target` usable episodes (default 400) and
backs off on Codex failures such as usage limits. The problem set is the
official warm-up file plus `benchmark_data_extra.jsonl`; both
`verify.load_benchmark` and `benchmark.py` read both.

- **The trace is `runs/<ep>/tools.jsonl`, not the Codex rollout.** Codex runs
  models in code mode (JavaScript cells calling tools, with state carried
  between cells), so the resolved arguments exist only in our MCP server's
  log.
- **Collect only with `--toolset student`.** That exposes exactly
  `student_tools.SCHEMA` and turns off Codex's shell. Legacy episodes (104,
  before `student-v1`) are not SFT data.
- **Changing a tool's name, arguments or output means bumping
  `student_tools.TOOLSET_ID`.** Never mix toolsets or `WRAPPER_ID`s in one
  mixture.
- **Mixtures are immutable** (`data/<mixture>/<version>/` plus a manifest
  written last). Make a new version; never overwrite one.
- **Loss is on assistant tokens only.** `train_sft.py` checks that the chat
  template renders each prefix of the conversation identically and refuses
  if not. Stock Qwen3 and OProver need `templates/qwen3_stable_think.jinja`
  (the default).
- **Splits are by problem name** (`training/splits.py`). Test problems are
  never collected on.

## Hard rules

- **One heavy Lean job at a time.** Concurrent `lake build`s or episodes have
  crashed the dev machine (a Raspberry Pi). `collect.py` is sequential; keep
  it that way.
- **Never wrap `arena.py` in an outer shell `timeout`.** It orphans `lake env
  lean` grandchildren. Every subprocess that can spawn Lean runs in its own
  process group and is killed with `os.killpg`. Copy that pattern.
- **Never spend paid credits or extra usage.** `collect.py` pauses a backend
  when its CLI-reported 5-hour window passes `--max-5h` or its weekly window
  passes `--max-week`. It stops outright if any run reports credits or overage
  in use. Claude runs are also capped per episode with `--max-budget-usd`.
  Don't loosen these without the owner's OK.
- **No OpenRouter spend without the owner's explicit OK.** Credits are
  limited. Codex CLI runs on a subscription and is the default. OpenRouter
  (`--backend openrouter --native-tools`) is a separate, later branch.
- **Decontamination:**
  - Teachers must not read prior episodes, traces, `mining/`, `docs/`, or
    `~/.codex/sessions`. Codex `-C` sets only the working directory, not a
    read restriction.
  - The student tool set enforces `_safe_path` and `_bash_leak_check`.
    `build_sft.py` also path-audits every trace.
  - Never put warm-up specifics (lemmas, scores, traces) into
    `prompts/refactor.md`.
- **Weak-subagent traces never go into SFT data.** Neither do episodes that
  used `apply_patch` or `spawn_agent`. `build_sft.py` drops them.
- **Scoring uses local references** (`competition/reference_measurements.jsonl`).
  Don't re-measure them unless you mean to replace that file.

## Klone (Hyak) notes

- Reach it with `ssh klone`. Training lives in
  `/gscratch/amath/aurasoph/lean-refactor-training`, and `HF_HOME` is
  `/gscratch/amath/aurasoph/hf_cache`. Compute nodes have no internet, so
  stage models with `training/setup_env.sh` on the login node.
- **Use `ckpt-g2` / `ckpt-amath`** (L40, L40S, H200; preemptible). The
  `gpu-rtx6k` Turing cards lack bf16 SDPA kernels and OOM on 20k-token
  traces.
- The Klone venv runs transformers 5.x: use `dtype=`, not `torch_dtype=`, and
  `warmup_steps`, not `warmup_ratio`.

## Checks before you push

```
python3 -c "import ast; [ast.parse(open(f).read()) for f in ['competition/arena.py','competition/student_tools.py']]"
python3 competition/local_score.py --self-check          # expect 0 MAE
python3 competition/collect.py --dry-run
python3 training/build_sft.py --mixture x --version x --dry-run
```
