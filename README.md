# Lean Refactor Arena

This repo is an entry for the [Lean Refactor Arena](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena):
take an existing Lean 4 proof and rewrite it to be shorter and cheaper to
elaborate. The statement must stay exactly the same, and the new proof must
still compile on every Lean toolchain the problem lists.

`competition/` is the harness. It prepares each problem inside pinned Lake
projects, one per toolchain. It lets an agent edit and compile a candidate
proof, and it scores that proof the same way the leaderboard does: length
reduction, heartbeat reduction, and cross-toolchain survival.

The closed-model track runs frontier models through Codex CLI and Claude Code
as agents inside that harness. Every agent gets the same small tool set:
read, search, compile, and submit-and-score.

The open-model track distills those agent runs into an open model.
`competition/collect.py` gathers traces on problems mined from the same
source libraries (never on the benchmark itself). `training/` then turns them
into a multi-turn dataset and fine-tunes an open Lean prover with LoRA.

To reproduce, see `docs/HANDOFF.md` for setting up the toolchains and
`AGENTS.md` for the day-to-day commands.
