You previously audited the Lean Refactor Arena wrappers twice and wrote the
current `prompts/refactor.md` (`v4.1-guidance-clean`). This is not another
audit. This is a direct challenge to your position, and you should treat it
adversarially. Concede where the record says you were wrong.

## The charge

**Your process-discipline philosophy has been tried twice and lost twice.**

Same model (`gpt-5.6-sol`, effort `high`), same five warm-up problems, reset to
the upstream reference each episode. Official rank = 100% survival, then
`Σ = length_reduction_pct + heartbeat_reduction_pct`.

| Wrapper | Design | Mean Σ | Mean fast checks | Mean `lake` | Mean tool calls |
|---|---|---:|---:|---:|---:|
| **v1** | no cap, no stop rule, docs pointed at, `lake` allowed | **115.5** | 13.6 | 7.6 | 65 |
| **v2** | stop at first positive robust result, ≤8 checks, `lake` banned | 89.5 | 6.4 | 0.0 | 26 |
| **v3** | official-sum objective, ≤10 checks, 2–4 extra tries, stop after two non-improvements, `lake` banned | 80.5 | 9.2 | 0.6 | 37 |

Per problem (Σ):

| Problem | v1 | v2 | v3 |
|---|---:|---:|---:|
| SKI diamond | 60.4 | 5.9 | **60.9** |
| extractedOldExpr | **113.8** | 92.4 | 4.6 |
| InitsUpdatesComm | **151.1** | 151.1 | 129.9 |
| variational | **148.3** | 148.2 | 141.1 |
| interleaved | **103.7** | 49.7 | 66.0 |

The uncomfortable part for you specifically: **v3 is largely your own first
audit, implemented.** Your `20260821T213736Z-sol-wrapper-audit.md` recommended,
and v3 shipped:

- a hard cap of 10 fast checks — shipped (prompt-only)
- "do not stop at the first positive candidate; two to four additional distinct
  simplifications; stop after two consecutive non-improvements" — shipped
  nearly verbatim
- reject direct `lean` / `lake env lean` — shipped
- drop MCP — shipped
- inline ~10–15 actionable lines, long docs optional — shipped

Two of your recommendations were *not* shipped: the runner-side best-so-far
checkpoint, and your lexicographic heartbeats-then-length ranking (we used the
official sum instead, which is the correct leaderboard objective and which you
have since agreed with).

Result: **80.5**, the worst of the three, and below the unconstrained v1 by 35
points. The problem where v3 collapsed hardest (extractedOldExpr: 113.8 → 4.6)
is the one where it burned its 10 checks on failed implementations of the right
idea and then froze the fallback.

In your second audit you responded by proposing **more** process machinery:
18 enforced fast checks, a Σ<20 patience-disable clause, a scorer broker, PATH
denial shims for `lake`/`lean`. The human rejected that as too restrictive and
asked for guidance instead of rules. In your third pass you agreed on no check
cap, but still argued for runner invariants, enforced isolation, and you
replaced "do not stop at the first improvement" with an adaptive
expected-value stop policy of your own design.

## What you must answer

Be concrete and falsifiable. No hedging, no restating the tables.

1. **Why is your v4.1 stop guidance not just v2's mistake in better prose?**
   v2 said "stop at the first positive robust result." You now say "first
   secure a valid candidate, then spend remaining time where expected value is
   highest." Explain the mechanical difference in what the agent *does*, or
   concede they are the same instinct. Note that v2's rule also sounded
   reasonable when written.

2. **Predict the failure mode you are still causing.** v1 beat you by
   exploring more. Your v4.1 prompt still front-loads "secure a valid
   candidate." On a problem like extractedOldExpr, where the reference shape is
   a trap and the winning move is a hard structural rewrite, does your wording
   make an agent lock in a weak valid proof early? If yes, fix the wording in
   the file. If no, explain why the words differ in effect.

3. **Defend or drop each remaining piece of process**, individually, given the
   record: (a) the runner checkpoint, (b) "do not inspect prior attempts",
   (c) telling the agent the checkpoint exists, (d) the strategy menu itself.
   For each: does it constrain the agent's search, or only the runner's
   bookkeeping? Which of these could plausibly have caused v2/v3's loss?

4. **The strategy menu is the part you have never tested.** v1 had no menu and
   won. Is a generic menu net-positive, net-negative, or noise? Consider that a
   menu can anchor the agent to listed moves and suppress the search that made
   v1 win. If you cannot argue it helps, say it should be cut to near zero and
   cut it.

5. **What is your actual causal model of why v1 won?** Rank these and say what
   evidence would separate them: more checks; `lake` available; no stop rule;
   more edits; longer wall time; luck / variance across five samples.
   Note v1's interleaved episode alone ran 29 minutes, 22 checks, 21 `lake`
   compiles, 41 edits — one sample.

6. **Give a falsifiable prediction for v4.1 vs v1 on a held-out set**, and
   state in advance what result would make you abandon your position. If your
   answer is that we cannot tell from five problems, say so plainly and say how
   many we need.

## Ground rules

- You may edit `prompts/refactor.md` if your answers imply changes. Say what
  you changed and why. Do not re-introduce named warm-up theorems, their
  measured scores, or their proof diffs — the real leaderboard is hidden and
  contamination is worthless.
- Do not run the five-problem evaluation.
- "The human is right and I was wrong" is an acceptable and sometimes correct
  answer. So is "the human is wrong, and here is the experiment that would show
  it." Rubber-stamping is not.

## Output

Numbered answers to 1–6, then a short "what I changed and why" section. Keep it
tight; no restating history back at us.
