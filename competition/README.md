# Lean Refactor Arena workspace

This directory is the local setup for the warm-up benchmark at [Lean Refactor Arena](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena).

## Projects

There is one pinned project directory per major Lean version used by the warm-up data:

`v4.25`, `v4.26`, `v4.27`, `v4.28`, `v4.29`, `v4.30`, `v4.31`, `v4.32`, and `v4.33`.

Patch releases are deliberately collapsed into their major/minor directory. Each directory still has a concrete representative `lean-toolchain` pin for Lake/Elan: the latest patch represented in that project (and `v4.33.0-rc2` for the 4.33 project). The per-problem source commits remain exact in the matrix.

Each project contains:

- `lean-toolchain`, identifying the major/minor toolchain family;
- `problems/`, with a copy of every benchmark row applicable to that version;
- `lakefile.toml`, a Lake manifest that depends on the relevant corpora (Strata, PhysLib, CSLib, ArkLib) and Mathlib via git, pinned to the exact commits recorded by the benchmark.

Lake fetches those packages on `lake update` / `lake build`; they are not vendored under this tree.

The canonical benchmark records remain in [`benchmark_data_warmup.jsonl`](benchmark_data_warmup.jsonl). The Space UI and its README live in the [Space repo](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/tree/main). `benchmark.py` and `leaderboard.py` stay here because the local scorer imports them.

## Harness

Three scripts, in the order you use them:

- [`local_score.py`](local_score.py) — the arena's scorer, mirrored. Length uses
  the ProofOptimizer lexer (exact on all 15 warm-up `proof_length`s) and the
  forbidden-pattern list is copied from the Space's `app.py` ([Space source](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/tree/main)). No house rules are
  added: `--self-check` scores the references and must report 0 MAE.
- [`verify.py`](verify.py) — compiles a candidate *inside* its real project and
  measures heartbeats. Project problems are spliced back into the prefix of their
  upstream source file (same imports / `open`s / `variable`s); PutnamBench
  problems use the row's `header`. `--measure-references` fills
  `reference_measurements.jsonl` with locally-measured reference heartbeats and
  the per-toolchain baseline.
- [`arena.py`](arena.py) — the episode harness:

```
python3 arena.py list                  # problems, toolchains, local env readiness
python3 arena.py prepare --name NAME   # write the work file into its project
python3 arena.py check   --name NAME   # compile + measure + score the work file
python3 arena.py run     --name NAME   # prepare → teacher → check → record
python3 arena.py run --name NAME --backend claude   # same, via `claude` (Opus)
python3 ../training/harvest_traces.py  # Codex rollouts → traces/{raw,distilled}/
```

See [`../docs/HANDOFF.md`](../docs/HANDOFF.md) if you just unpacked this tree on a new machine.

`check` is the only scoring tool the agent is given; `run` records an episode to
`../runs/episodes.jsonl` with the before/after metrics. `runs/` and `traces/`
live *outside* this directory deliberately — it is the working directory,
not a read sandbox. An agent can still read `../runs` or `~/.codex/sessions`.
Keeping transcripts off the default search path still helps (this was a real,
observed failure mode before the move). Codex session ids are what `../training/harvest_traces.py` resolves into
a trace (Claude logs stay in `../runs/<stamp>-*/claude.jsonl`).

Two more pieces layered on since the sections above were written:
`mcp_server/` (custom tools exposed to the `codex` backend over MCP —
`get_target`, `evaluate_candidate` — see its own `server.py`). Candidate
mining lives in `../mining/` (`find_problems.py`, `promote_discovered.py`,
`discovered_problems.jsonl`) so extra theorems are not in the teacher's
working directory. Trace harvest lives in
`../training/harvest_traces.py`.
`arena.py run` also supports
`--backend openrouter` and `--backend codex --model <any codex-cli model>`,
not just `claude`.

**Heartbeat measurement.** `#count_heartbeats` only exists in Mathlib, so
`verify.py` defines the same measurement locally (`IO.getNumHeartbeats` delta /
1000, with `Elab.async false` — without that, async elaboration hides the work
and counts come out ~100× too low). All 15 references reproduce: the three
standalone PutnamBench proofs match to within 3 heartbeats, and the in-repo
problems run +0.2% to +18% high (the injected measurement command perturbs the
environment slightly, which matters most on the 1.4k-heartbeat CSLib problem).
The offset is systematic, so reductions are scored against the *locally
measured* reference in `reference_measurements.jsonl` rather than the published
number. That sweep also confirms every reference proof compiles on every
toolchain its row lists, so a failing `compat` entry is the candidate's fault.

Heartbeats are compared on the **newest** toolchain in a problem's
`version_info`; that is the one the published references reproduce on.

## Warm-up inventory

The current data has 15 problems across five corpora:

- Strata: 3 problems, Lean 4.25–4.29;
- PhysLib: 3 problems, Lean 4.29–4.32;
- CSLib: 3 problems, Lean 4.30–4.33;
- ArkLib: 3 problems, Lean 4.28–4.31;
- PutnamBench: 3 standalone problems, Mathlib 4.25–4.27.

All problem copies include the original statement/proof and a header recording the source and exact commit for that version.

## Rules and grading summary

Each submitted proof must preserve the benchmark statement, compile, avoid `sorry` and forbidden constructs, and be replayed unchanged across the problem's listed toolchains. The score is the mean of:

1. proof-length reduction versus the reference token count;
2. heartbeat reduction measured with Lean's `#count_heartbeats`;
3. zero-shot transfer, the fraction of listed toolchains where the proof still compiles.

Closed-source track: API spend is capped at US$3 per problem. Open-source track: the full run must fit within 48 hours on at most four 80 GB A100 GPUs. Submissions also require JSONL proofs, reproducible harness/inference code, and a short OpenReview technical report covering approach, models, budget accounting, and reproduction. See the Space's `competition-README.md`, `app.py` ([Space source](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/tree/main)), and the Space's `contribution.md` for the retained source text.

## Important setup note

The repository-resident problems are intentionally copied as source records. Building a version project requires Lean/Lake (via Elan) and a network fetch of the pinned corpus commits (and their transitive deps); no theorem text or version mapping has been altered during this setup.
