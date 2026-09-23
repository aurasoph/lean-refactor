# Handoff — Lean Refactor Arena (updated 2026-09-22)

Working copy of the local harness for the
[Lean Refactor Arena](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena)
open track. This is now a real git repo (`git clone` it, don't unzip). This file is just
the "how do I get a runnable machine" doc.

The repo does **not** include `competition/projects/*/.lake/` (many tens of
GB of Mathlib oleans and git checkouts per toolchain) or
`competition/.corpus_cache/` (downloaded upstream corpus source, ~27 GB).
Those rebuild from `lake-manifest.json` + `build-all.sh`; there's no shortcut
to skip that rebuild unless you copy someone else's already-built `.lake`
directories directly (rsync, not git).

---

## Clone

```
git clone <this repo's URL>
cd lean-refactor-arena
cd competition   # harness commands below assume this cwd
```

The repo root's meaningful children are `docs/` (plans), `competition/`
(the harness), `mining/` (candidate discovery), `runs/` + `traces/`
(episode data), and `training/` (harvest + SFT). `runs/` / `traces/` /
`mining/` live **outside** `competition/` deliberately — that directory is
the teacher's working directory, not a read sandbox. An agent can still
read `../README.md` or `~/.codex/sessions`. Don't move them back under
`competition/` (default search path / convention until `bwrap` lands).

---

## What this is

Goal: an open-weight model + open harness that rewrites an existing Lean 4
proof to be shorter and cheaper, with full toolchain survival, for the
open-source track — fed by closed-teacher episodes run for the closed-source
track (both tracks are real competitive entries; the closed track is also
the open track's data source). See the tech report for the full research
agenda and competition rules summary.

---

## Layout

Paths relative to the **repo root**. Harness commands in the cheat sheet
still assume `cwd=competition/`.

| Path | What |
|---|---|
| `competition/arena.py` | Episode harness: `prepare` / `check` / `run` / `list` / `usage` / `rescore` / `prompt` |
| `competition/verify.py` | Real compile + heartbeat measurement inside each version project |
| `competition/local_score.py` | Length + forbidden-pattern scorer (mirrors the Space) |
| `competition/mcp_server/server.py` | Custom tools (`get_target`, `evaluate_candidate`) exposed to the `codex` backend over MCP |
| `mining/promote_discovered.py` | Compile-verifies candidates from `discovered_problems.jsonl` against built toolchains, promotes real passes |
| `mining/discovered_problems.jsonl` | Mined candidate problems (3,226 rows), mostly unverified |
| `training/harvest_traces.py` | Codex rollouts → `traces/{raw,distilled}/` |
| `competition/prompts/refactor.md` | Teacher prompt. Current id: **`v4.2-minimal`** |
| `docs/rho-reference.md` | Axiom Rho config reconstruction — **not our plan**, kept as a cost/scale anchor |
| `runs/episodes.jsonl` | Every episode |
| `runs/trials/` | Every `check` call (scored candidates) |
| `runs/<stamp>-<problem>/` | Per-episode before/after Lean + teacher log |
| `traces/` | Harvested rollouts |
| `training/` | Trace harvest + SFT data prep + LoRA + Hyak Slurm jobs |
| `competition/projects/v4.25` … `v4.33`, `v4.29.1` | One Lake workspace per toolchain family |
| `competition/benchmark_data_warmup.jsonl` | Canonical 15-problem warm-up |
| `competition/reference_measurements.jsonl` | Locally measured reference heartbeats — **scoring uses these** |
| `competition/build-all.sh` | Sequential `lake update` + `lake exe cache get` + `lake build` |
| `docs/VERSION_MATRIX.md`, `docs/STRATEGY.md` | Toolchain matrix and Lean golfing tactic notes |

`WRAPPER_ID` and defaults live at the top of `arena.py`:

- wrapper: `v4.2-minimal`
- teacher default: Codex `gpt-5.6-sol`, effort `high`
- `--backend codex --model gpt-6-astra` also works (same CLI, different
  model) and currently performs best — free on an existing Codex/ChatGPT
  subscription, native tool-calling, plus the two custom MCP tools above.
  `--use-octo` additionally registers Axiomatic Octo (semantic search) as a
  second MCP server, codex backend only.
- `--backend openrouter` is metered (real $/token) — pass `--native-tools`
  to use real function-calling instead of the older text-fenced protocol
  (the text-fenced one measurably underperforms). **Don't run
  this backend without confirming there's budget for it first** — OpenRouter
  credits are limited and not always topped up.
- `--backend claude` uses the `claude` CLI, model `opus`.

---

## Restore the Lean environment

Needs: Elan, a working `lake`/`lean` on PATH, git, network. Hours, not
minutes, and **build toolchains strictly one at a time** — running several
concurrent `lake build`s has crashed this machine before (a Raspberry Pi;
adjust expectations for your hardware, but sequential is still safer).

```
# toolchains used by the projects (check each lean-toolchain file)
elan toolchain install leanprover/lean4:v4.25.2   # example — install whatever each file pins
# …

cd competition
./build-all.sh                 # all version projects, one at a time
# or one: ./build-all.sh v4.31
python3 arena.py list          # env=. / env=x means built / not built for that toolchain (live filesystem check)
```

`build-all.sh` skips `lake update` only when **both** `lake-manifest.json`
and `.lake/packages` exist. On a fresh clone it will fetch.

Heartbeat scoring is against **local** references in
`reference_measurements.jsonl` (the injected measurement command
systematically inflates some in-repo proofs). Do not re-run
`--measure-references` unless you intend to replace that file.

Smoke:

```
python3 local_score.py --self-check    # expect 0 MAE on the 15 references
python3 arena.py prepare --name "Core.InitsUpdatesComm" --force
python3 arena.py check   --name "Core.InitsUpdatesComm" --all-versions
```

## Auth needed for teacher backends

- `codex` backend: `codex` CLI installed and logged in (ChatGPT/Codex
  subscription). No API key needed.
- `openrouter` backend: `OPENROUTER_API_KEY` env var.
- `claude` backend: `claude` CLI on PATH, logged in.
- `mcp_server/` needs its own venv (`python3 -m venv mcp_server/venv &&
  mcp_server/venv/bin/pip install -r mcp_server/requirements.txt`).
- `training/` needs torch (its own install command, CUDA-build-dependent —
  see `training/requirements.txt`'s top comment) plus
  `training/requirements.txt`; see `training/setup_env.sh` for the exact
  sequence used on Hyak.

---

## Run a teacher episode

```
# Sol (default)
python3 arena.py run --name "Core.InitsUpdatesComm"

# Astra, currently the best-performing setup
python3 arena.py run --name "Core.InitsUpdatesComm" --backend codex --model gpt-6-astra --effort high

# Opus via Claude Code CLI (must be logged in: `claude` on PATH)
python3 arena.py run --name "Core.InitsUpdatesComm" --backend claude --effort high
```

`run` resets the work file to the reference, invokes the teacher with
`prompts/refactor.md`, then `check --all-versions`, then **runner-side
checkpoint recovery**: if the agent's last write is invalid or worse than a
fully-surviving earlier candidate (including the reference), the submitted
artifact is rolled back. That is why a crashed teacher can still record Σ = 0
with 100% survival — that's the safety net working, not a bug (see the
`eligible` field on `check`'s output, which makes this explicit rather than
letting a failed candidate's raw numbers look like a real score).

`check` is the only scorer the agent should use. `lake env lean` is the cheap
error loop (no score). Official objective:

```
combined = (length_reduction_pct + heartbeat_reduction_pct + survival_pct) / 3
rank among 100% survivors by objective_sum_pct = length + heartbeat reductions
```

`arena.py usage` gives a per-episode token/cost breakdown across all past
runs, computed by re-parsing each run's raw teacher log — useful for
checking real spend without re-running anything.

After Codex episodes:

```
python3 ../training/harvest_traces.py
```

Harvest looks up `~/.codex/sessions` by session id — those session files are
machine-local, not in the repo. Claude episodes log to
`../runs/<stamp>-*/claude.jsonl`; harvest does not ingest those yet.

---

## Design choices that matter on the next machine

- **Decontaminate.** The live board will have hidden problems. Do not put
  warm-up-specific lemmas, scores, or episode traces into
  `prompts/refactor.md`. `runs/`/`traces/` live outside `competition/` so
  they are not on the default search path — an agent reading a prior episode
  via `cd ../runs` actually happened once. That is a convention, not a read
  restriction (Codex `-C` sets cwd; `~/.codex/sessions` is still readable).
  `_bash_leak_check` in `arena.py` guards the openrouter `bash` tool against
  `runs`/`traces`/`mining`/`docs/`/`.codex/sessions` as well.
- **Guidance, not stop-rules.** An earlier, more prescriptive wrapper
  generation lost to a more minimal one that states the objective and gets
  out of the way. Safety net is checkpointing, not a prompt cap.
- **Do not mix wrapper generations** in one SFT set. Each prompt version
  taught a different stopping policy. Traces are labeled with `wrapper`.
- **Never wrap `arena.py` invocations in an outer shell `timeout`.** Its own
  internal `timeout=` parameters already manage subprocess cleanup
  correctly; an outer `timeout` SIGTERMs the parent Python process without
  reaching already-spawned grandchild `lake env lean` processes, which then
  run orphaned indefinitely. Happened live, more than once. `verify.py`'s
  `run_one` now also runs its own subprocess in its own process group and
  kills the whole group on its internal timeout, for the same reason one
  level down.
- **Build toolchains sequentially, never concurrently.** Also happened live
  — 5 concurrent `lake build`s crashed the development machine once.

---

## Not in this repo (gitignored — see `.gitignore` at the repo root)

- `competition/projects/*/.lake/` — rebuild or copy separately
- `competition/.corpus_cache/` — downloaded upstream corpus source cache
- Elan toolchains (`~/.elan`)
- Codex/Claude session files (machine-local)
- API keys / auth — see "Auth needed" above
- `mcp_server/venv/`, `mcp_server/octo_venv/` — local Python venvs
- `../mining/promotion_staging.jsonl` was previously gitignored as a
  working file under `competition/`; the currently-verified rows have since
  been committed — check whether a newer, not-yet-reviewed version exists
  locally before assuming the committed one is current.

---

## Commands cheat sheet

```
python3 arena.py list
python3 arena.py usage
python3 arena.py prompt --name NAME
python3 arena.py prepare --name NAME --force
python3 arena.py check --name NAME
python3 arena.py check --name NAME --all-versions
python3 arena.py run --name NAME
python3 arena.py run --name NAME --backend codex --model gpt-6-astra --effort high
python3 arena.py run --name NAME --backend claude --effort high
python3 arena.py rescore --name NAME --run-dir RUN_DIR
python3 ../mining/promote_discovered.py --source strata cslib --min-confidence 5
python3 ../training/harvest_traces.py
python3 ../training/harvest_traces.py --name NAME
./build-all.sh
```
