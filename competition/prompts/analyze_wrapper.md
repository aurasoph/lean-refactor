You are not competing. You are auditing the **v4-guidance** Lean Refactor Arena
wrapper, then you may edit the prompt if you have a better version.

Goals: (1) an optimal competition wrapper for Sol on the *official* mean
leaderboard, (2) traces worth keeping as data. The live hidden test set will
not be these warm-up problems — **do not propose anything that would only
help because it leaks a known solution.**

## You are invited to disagree

The human's current view (after v1–v3):

> v1 won because we mostly let Sol do what it wants. Wrappers should be
> guidance, tips, and examples of strategies that work — not constraints.
> Caps, stop rules, patience counters, and PATH shims are too strict in a
> way that is not productive.

That view is a hypothesis, not a requirement. **Push back if the data or
Lean-agent behavior disagrees.** In particular, consider:

- Prompt-only "no cap" vs a *runner* checkpoint (v4 already checkpoints
  best-so-far after the episode; the agent is not capped).
- Whether "do not stop at the first improvement" is still a rule dressed as
  advice, and whether some *light* process constraints actually help.
- Whether restoring `lake env lean` is correct, or whether it just correlated
  with v1's extra search.
- Whether 30 minutes / `high` effort is the right budget.
- Whether harvest and leaderboard wrappers should differ.

Say when you agree, when you don't, and what you would do instead. Do not
rubber-stamp the human.

## What already ran (same model `gpt-5.6-sol`, effort `high`, same five)

Official rank: 100% survival, then `Σ = length% + heartbeat%`.

| Problem | v1 Σ | v2 Σ | v3 Σ | v1 min | v2 min | v3 min | v1 fast+lake | v2 fast | v3 fast |
|---|---|---|---|---|---|---|---|---|---|
| SKI diamond | 60.4 | 5.9 | **60.9** | 5.5 | 6.5 | 3.6 | 6+0 | 9 | 6 |
| extractedOldExpr | **113.8** | 92.4 | **4.6** | 8.5 | 5.6 | 6.3 | 17+8 | 9 | 10 |
| InitsUpdatesComm | **151.1** | 151.1 | 129.9 | 6.2 | 2.7 | 6.5 | 9+6 | 3 | 11 |
| variational | **148.3** | 148.2 | 141.1 | 11.9 | 5.7 | 6.7 | 14+3 | 6 | 9 |
| interleaved | **103.7** | 49.7 | 66.0 | 29.4 | 5.9 | 18.3 | 22+21 | 5 | 10 |

Means: v1 **115.5 Σ / 62 min**; v2 **89.5 / 26 min**; v3 **80.5 / 41 min seq**.
v1 used more search (mean 13.6 fast checks + 7.6 `lake`). v2 capped at 8 and
stopped at first green. v3 stated the official sum, capped at 10, banned
`lake`; SKI traded length for heartbeats correctly, then collapsed on
extractedOldExpr (right idea, failed implementation, froze the fallback).

Prior Sol audit (`runs/analysis/20260821T224647Z-sol-v4-audit.md`) proposed
**v4-A** with 18 enforced fast checks, Σ<20 patience disable, PATH denials,
scorer broker. The human rejected that as too restrictive. Current v4 is the
guidance rewrite plus a *silent* runner checkpoint (not a search cap).

## Current wrapper (this is what you audit)

Root: `/Users/evanwang/Lean_Refactor/competition`

- `prompts/refactor.md` — **v4-guidance**, just decontaminated: no named
  warm-up theorems, no measured % from our five, no real proof diffs. Generic
  strategies only. `lake env lean` is allowed again. No check cap / stop rule.
  Agent is told not to read `runs/` or `traces/`.
- `arena.py` — `WRAPPER_ID = "v4-guidance"`, `DEFAULT_EFFORT = "high"`. Every
  `check` appends to `runs/trials/<slug>.jsonl`. After Codex exits,
  `best_checkpoint` restores the highest-Σ 100%-surviving candidate seen this
  episode (tested: a ruined ending recovered 151.13).
- Optional long notes: `docs/STRATEGY.md`, `docs/LEAN_SYNTAX.md`, `docs/VERSION_MATRIX.md`
  (community playbook, not our five solutions — still flag if you see leakage).

The five A/B problems are still the local eval set. Hidden leaderboard
problems will not match them. Contamination that only helps these five is
worthless.

## What to do

1. Read `prompts/refactor.md` and the checkpoint code in `arena.py` end to end.
2. Hunt remaining contamination: named theorems, distinctive snippets, "33% /
   80%" style scores, pointers at `runs/`/`traces/`, STRATEGY.md leaks.
3. Push back (or not) on guidance-vs-rules, with a concrete alternative if you
   disagree.
4. You **may edit** `prompts/refactor.md` (and small `arena.py` comments / ids)
   to decontaminate further or to add *light* process help you believe in.
   Do **not** re-introduce named warm-up solutions, check caps, or PATH shims
   unless you argue hard for them in the report. Do not run the five-problem
   eval.
5. Optional: one `arena.py check` on a dummy edit is fine; don't golf.

## Output

A short report:

- Remaining contamination, if any (and what you changed).
- Where you agree / disagree with "guidance not rules", and why.
- The wrapper you now recommend (prompt shape + runner), vs harvest-only if
  different.
- What you would measure next (without proposing we overfit the five).
