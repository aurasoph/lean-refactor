## Audit result

I recommend the revised wrapper in [prompts/refactor.md](/Users/evanwang/Lean_Refactor/competition/prompts/refactor.md). I also bumped the ID to `v4.1-guidance-clean` in [arena.py](/Users/evanwang/Lean_Refactor/competition/arena.py:38). Prompt rendering and Python syntax pass; I did not run the five-problem evaluation.

### Contamination

The active prompt had two residual problems:

- It linked `VERSION_MATRIX.md`, which explicitly names every warm-up.
- It linked `STRATEGY.md`, which contains named benchmark measurements, warm-up counts, and local-rig priors.
- It advertised the exact `runs/` and `traces/` locations while warning against reading them.
- Several supposedly generic examples were strongly shaped around the warm-ups.

I removed those links, paths, measurements, and tailored pseudo-diffs. The prompt now prohibits reading prior attempts generically without pointing to them.

The supporting files remain physically readable, so prompt compliance is still the only barrier. For uncontaminated local traces, I would stage episodes in an allowlisted task directory containing only the work file, project/corpus, scorer, and generic prompt. That is data isolation, not a PATH or search restriction.

### Guidance versus rules

I agree with no agent check cap. The v1–v3 results support allowing more exploration, although they do not isolate search count from prompt quality and task variance.

I disagree that everything should be guidance:

- Validator requirements and full survival are real hard constraints.
- A known-good baseline and correct checkpoint recovery should be runner invariants.
- Prior-attempt isolation should be enforced for trustworthy evaluation data.

I replaced “do not stop at the first improvement” with an adaptive policy: secure a valid candidate, compare materially distinct shapes when plausible, and stop searching when polishing or verification has higher expected value.

Restoring `lake env lean` is correct on its own merits: it is a cheap compile-error loop. Its association with v1’s better result does not prove it caused the win, but banning it only makes diagnosis more expensive.

`high` effort and roughly 30 minutes are defensible defaults, not established optima. Also, the 30 minutes is currently prompt-only—`run_codex` has no outer timeout.

### Recommended runner

Keep the prompt-guided search plus runner checkpoint, but fix [best_checkpoint](/Users/evanwang/Lean_Refactor/competition/arena.py:259):

- Seed recovery with the original 100%-surviving proof.
- Reuse already-all-version-checked trials.
- Examine candidates by descending score until the highest surviving one is found, rather than stopping after three failed promotions.
- Scope trials by episode UUID, not only problem name and timestamp.

Currently, three higher-scoring incompatible candidates can hide a lower fully surviving candidate. If the agent finishes invalidly and all three promotions fail, the invalid ending can be restored instead of the original.

For leaderboard runs, use the revised strategy menu and disclose that checked candidates are recoverable. For harvest-only runs, use a more minimal prompt without strategy suggestions, while keeping the same safety checkpoint. Label the two trace populations separately.

The distilled traces should record wrapper ID/prompt hash and both `agent_final` and `checkpoint_after`. At present they only attach the restored score, potentially crediting the agent’s final actions with a runner-restored candidate.

### Measure next

On a fresh, broader held-out sample:

- Minimal prompt versus generic strategy menu.
- Silent versus disclosed checkpoint.
- `high` at 20/30/45 minutes; only then compare `max`.
- Final score and survival, plus score-over-time, distinct checked candidates, all-version failure rate, checkpoint promotion rate, and final-to-best regret.

Pre-register the comparison and do not use the five warm-ups to choose the winning arm.