You are refactoring one Lean 4 proof for the Lean Refactor Arena.

## Target

- Theorem: `{name}`
- Corpus: {source}
- Work file (edit this file, nothing else): `{work_file}`
- Lean project root: `{project_dir}` (toolchain {primary_version})
- Must also compile unchanged on: {other_versions}

The work file is the prefix of the upstream source file (imports, `open`s,
`variable`s, section context) followed by the target declaration with its
original proof. Everything above the declaration is context: do not touch it.
Scoring re-splices your declaration into the pristine upstream file, so any edit
you make above the declaration is discarded — only the declaration counts.

## Official objective

Maximize the arena leaderboard score, not length or heartbeats separately:

`combined = (length_reduction_pct + heartbeat_reduction_pct + survival_pct) / 3`

Full survival on every listed toolchain is a hard constraint. Among candidates
that survive everywhere, rank by:

`objective_sum_pct = length_reduction_pct + heartbeat_reduction_pct`

This is a real tradeoff, and the sum is the only tiebreak. A longer proof wins
when its heartbeat gain exceeds its length loss; over-golfing tokens loses if
elaboration gets sufficiently more expensive. Compare the sum printed by
`check` rather than reasoning about it.

References for this problem: {ref_heartbeats} heartbeats and {ref_length} proof
tokens.

## How to work

You have roughly 30 minutes of wall clock and no cap on tool calls or checks.
First secure a valid candidate. Then use the remaining time where it has the
highest expected value: compare materially different proof shapes when there
are plausible alternatives, or polish and verify when the proof already looks
structurally direct. A first improvement is evidence, not an automatic stopping
point or a reason to keep searching aimlessly.

Two feedback loops, and using the right one for each purpose matters:

```
cd {project_dir} && lake env lean Arena/{work_file_name}   # fast, errors only, no score
cd {competition_dir} && python3 arena.py check --name "{name}"                 # newest toolchain + score
cd {competition_dir} && python3 arena.py check --name "{name}" --all-versions  # + survival across toolchains
```

Iterate on *compile errors* with `lake env lean` — it is cheaper and you can
run it as often as you like. Use `check` when you want to know whether a
compiling candidate is actually better, and `--all-versions` to confirm a
candidate you intend to submit. `check` is the scorer, and its heartbeat number
is the one that counts; do not try to measure heartbeats yourself.

The runner records candidates passed to `check` and can revalidate a better
checked candidate after the episode. Use `check` on any compiling candidate you
would regret losing; a candidate seen only by `lake env lean` is not a scored
checkpoint. Leave enough time to run `--all-versions` on a strong candidate.

Use `rg`/`sed` on the corpus under `.lake/packages` freely — finding the right
existing lemma is usually what produces a large win. Do not use Lean MCP tools.

## Strategy menu

Choose tactics from the actual declaration and score feedback; none of these is
a requirement:

- Search nearby source and imported packages for a theorem that subsumes a
  repeated argument or an induction. Inspect its type and version availability
  rather than guessing from its name.
- Reconsider what to induct on. Induction over a derivation or invariant can
  expose stronger induction hypotheses and impossible cases; induction over
  data can be better when the recursive shape itself drives the proof.
- Compare automation with explicit proof terms. Removing broad search often
  saves heartbeats and improves stability, but a short closing tactic can still
  win the official sum. Measure both when the tradeoff is unclear.
- Factor genuinely repeated work into a local `have`/`let`/`suffices`. Do not
  add a top-level helper.
- After structural choices, try low-risk term simplifications such as direct
  projections, constructors, `rfl`, `rwa`, transport, or an inlined term found
  by a suggestion tactic. Explicit arguments can either reduce expensive
  inference or add needless tokens, so let `check` decide.
- Prefer APIs and proof behavior that exist across the listed toolchains. A
  shorter current-version proof is worthless if it loses full survival.

## Reading the score

- Treat `objective_sum_pct` as the arbiter. Neither fewer tokens nor fewer
  heartbeats alone proves that a rewrite is better.
- Use compile errors to distinguish a bad idea from an elaboration detail, but
  abandon an experiment when the remaining repair cost is no longer the best
  use of time.
- On an older-toolchain failure, inspect the diagnostic. Common causes include
  API drift, elaboration differences, tactic behavior, and normal-form changes;
  prefer a repair that remains explicit and portable.

## Hard rules

These come from the competition's upload validator, not from us. Everything
else about how you work is your call.

- The statement must stay **byte-identical**, including binders and
  implicit/instance arguments. Only the proof after `:=` may change.
- The submission is *the statement plus one proof, nothing else*. Do **not**
  add any top-level declaration: no `lemma`/`theorem` helpers, no `def`,
  `abbrev`, `instance`, `structure`, `inductive`, `class`, `opaque`,
  `attribute`, `macro`, `notation`, `syntax`, `deriving instance`, and no new
  top-level `set_option ... in` / `open ... in` beyond whatever the statement
  already carries. Factor shared work into `have`/`let`/`suffices` **inside**
  the proof.
- Forbidden anywhere in the proof: `sorry`, `admit`, `axiom`, `native_decide`,
  `ofReduceBool`, `ofReduceNat`, `#eval`, `#reduce`, `#exit`, `IO.*`,
  `unsafe`, `extern`, `initialize`, `run_cmd`, `run_elab`,
  `#count_heartbeats`, `@[implemented_by]`, `@[extern]`.
- No `set_option maxHeartbeats` to make something fit; the metric is a counter
  delta, so raising the limit scores nothing and hurts survival.
- Do not inspect prior attempts, saved candidates, episode analyses, or agent
  traces. They are not part of the problem and will not exist on hidden tasks.
- Do not edit any other file, do not edit anything under `.lake/`, and do not
  change the project's toolchain or dependencies.

## When you are done

Leave your best proof in the work file as the last declaration, confirmed by an
`--all-versions` check. Reply with: what you changed, final length and
heartbeats versus the reference, the `objective_sum_pct` you reached, which
toolchains pass, and which rewrites you tried that did not work.
