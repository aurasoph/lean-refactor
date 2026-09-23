## Checks performed

| Proof checked | Scope | Len reduction | HB reduction | Result |
|---|---:|---:|---:|---|
| SKI v1 restored | 4 versions | 15.23% | 45.18% | Same as v1; decisively beats v2’s 0.49% / 5.40% |
| Interleaved v1 restored | 3 versions | 54.18% | 49.51% | Same as v1; beats v2’s 30.67% / 19.02% |
| Interleaved golf A | newest only | 54.77% | 49.28% | Shorter than v1, but heartbeat-worse |
| Interleaved golf B | newest only | 54.62% | 49.48% | Nearly ties v1 HB, but still heartbeat-worse |

The interleaved v1 restore plus full check took roughly 42 seconds, demonstrating that the strong proof itself does not require another 29-minute search. Under the stated heartbeat-before-length ordering, v1 remains the winner.

The work files now contain the better v1 proofs:

- [SKI proof](/Users/evanwang/Lean_Refactor/competition/projects/v4.33/Arena/Cslib_SKI_parallelReduction_diamond.lean:139)
- [Interleaved proof](/Users/evanwang/Lean_Refactor/competition/projects/v4.31/Arena/interleaved_affine_gaps_imply_tensor_gaps.lean:1208)

InitsUpdatesComm was byte-identical across v1/v2, so its 214-second speedup is wrapper/search overhead, not proof quality.

## What v2 got right and wrong

Right:

- It cut total wall time from 62 to 26 minutes.
- Every episode used only one final all-version sweep.
- InitsUpdatesComm reached the identical optimum in 159 rather than 373 seconds.
- Removing MCP was correct; neither run used it.
- Contrary to the apparent “lake once” observation, the distilled v2 tool calls contain no direct `lake env lean`. They do search source under `.lake/packages`, which is useful and should remain allowed. Actual compiler duplication was concentrated in v1: interleaved used 22 fast checks plus 21 direct Lake compiles; Call used 16 plus 8.

Wrong:

- “Stop at the first positive robust result” optimizes wall time too aggressively. Interleaved stopped after its first compiling candidate; SKI exhausted its search without finding v1’s compact constructor formulation.
- The cap is prompt-only. SKI and Call each used eight real fast checks plus `arena.py check --help`, producing the observed ninth checker invocation.
- The runner does not preserve the best candidate automatically. This encouraged commented-out backups and risks losing a better heartbeat candidate while golfing length.
- Mandatory reading is excessive: the four files total 844 lines. Agents dutifully read them, sometimes through several calls, but corpus/theorem searches drove the useful decisions. Inline the small actionable subset; leave the files optional.
- SKI shows a search-quality failure, not merely a stop-rule failure: v2 expanded compact constructor terms into verbose `use`/`exact` blocks.

## Concrete v3 changes

Tool-side, not merely prompt-side:

- Expose counted `fast_check` and `all_versions_check` operations; reject calls past the cap.
- Reject `check --help`, direct `lean`, and direct `lake env lean`.
- Keep `rg`/`sed` access to `.lake/packages`.
- On every successful fast check, automatically checkpoint the lexicographically best proof: lowest heartbeats, then shortest length. Restore it before the final sweep.
- Do not attach Lean MCP.
- Replace mandatory doc reading with roughly 10–15 inline lines: retain compact constructor terms, prefer explicit stable lemmas, measure every candidate, and never trade lower length for higher heartbeats. Make the long notes optional.

For the leaderboard wrapper, I would use a hard cap of 10 fast checks and this stop rule:

```text
Maintain an incumbent among candidates that compile and beat both references:
fewer heartbeats wins; if heartbeats tie, shorter length wins. Do not stop at
the first positive candidate. After finding one, try at least two and at most
four additional distinct simplifications, stopping early only after two
consecutive checks fail to improve the incumbent. Never re-run an unchanged
candidate. At 10 fast checks, restore the incumbent and run one all-version
check. If every version passes, stop immediately. If compatibility fails,
make only compatibility-directed repairs, with at most two further fast checks
before repeating the all-version check.
```

For trace harvesting, use six fast checks and exactly one consolidation attempt after the first positive candidate. Require each edit to state one hypothesis before checking. This loses some leaderboard score, especially on interleaved, but produces shorter, decision-dense traces without repeated errors.

For production leaderboard runs, seed from the best known proof rather than resetting to the upstream reference. For controlled wrapper comparisons, continue resetting, but keep the cross-run incumbent outside the agent.

## Training traces

Good full imitation traces:

- `20260820T224127Z-Cslib_SKI_parallelReduction_diamond`: strong final proof and relatively bounded search.
- `20260821T202343Z-Core_InitsUpdatesComm`: best example—same optimum in less than half the time.
- `20260821T201800Z-CallElimCorrect_extractedOldExprInVars`: clean bounded search with a strong heartbeat result.
- `20260821T202628Z-fundamental_theorem_of_variational_calculus'`: useful efficient trace, labeled as a length-versus-heartbeat tradeoff.

Keep only as cropped or preference data:

- `20260820T231405Z-interleaved...`: preserve the successful suffix and final proof, not the full 22-check/21-Lake trajectory.
- `20260820T224711Z-CallElimCorrect...`: strong solution, but crop the duplicated compilation and thrash.
- Pair v1/v2 SKI and interleaved as preference examples showing why “first positive” is inadequate.

Do not use as positive imitation:

- v2 SKI; retain only as a labeled failure/search-strategy counterexample.
- v1 InitsUpdatesComm; v2 is an identical-result, faster replacement.
- Full raw v1 interleaved trace.