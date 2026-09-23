# Lean Refactor Arena — scoring strategy playbook

Working notes on how to maximize the three-part score (length ↓, heartbeats ↓,
cross-version survival ↑) under the arena's validity rules. Grounded in what
Lean maintainers say on Zulip. Nothing here is settled; treat it as a hypothesis
set to test against `benchmark_versions`.

## The organizing insight

A minimal **term-mode** proof can win all three metrics at once — **but only up
to ~3 lines**. Above that, robustness diverges from length and you must choose.

Two reasons the axes are coupled at the low end:

- **Heartbeats and robustness are the same thing causally.** A proof that only
  survives via a raised `maxHeartbeats` is running at the search-budget cliff;
  any version that makes search slightly heavier tips it over. Low search ⇒ low
  heartbeats ⇒ far from the cliff ⇒ survives version sweeps. A term-mode `exact`
  has ~zero search, so it is simultaneously shortest, cheapest, and most
  durable. (Kim Morrison's Tau Ceti rule: no `set_option maxHeartbeats`
  anywhere. Alex Meiburg's CStar example worked only at 2× heartbeats → broke on
  a bump.)
- **Term mode is measurably faster, not just shorter.** Buzzard measured the
  same lemma at 168 ms (tactic) vs 31 ms (term golf). Mario: "all other things
  being equal, term-mode proofs are faster."

**Where it breaks (~3 lines):** Mathlib reviewers deliberately prefer a longer,
decomposed proof (named `have`s, `calc`) over a golfed term. Violeta Hernández:
"anything larger than two or three lines, we value maintainability over
performance." Jireh Loreaux calls the alternative "over-golfing." A giant nested
term concentrates fragility — one defeq/normal-form shift kills the whole term.

## Correction: don't oversell `exact?`

You cannot get raw length-minimality **and** cross-version survival from the same
found-lemma term. `exact?` finds whatever lemma exists in the *current* Mathlib,
and obscure / recently-added names are the first things to rename / deprecate /
move across a version sweep. `exact? → exact Foo.bar_of_qux` is short but
crushes `survival_rate`.

You submit **one** proof, so the real target is neither "shortest" nor "most
robust" — it is:

> the shortest proof drawn **only** from machinery invariant across **every**
> `benchmark_versions` entry.

That intersection is much smaller than the current-version toolbox. It is
dominated by:

- **Core/defeq term proofs** — `rfl`, `⟨…⟩`, `.1/.2/.mp/.symm`, `▸`, `nofun`,
  eta. These reference no `simp` set, so there's nothing to rename; they survive
  by construction. *This* is robust term-golf, not the `exact?` kind.
- **Deterministic algorithmic tactics** — `omega` above all (Presburger, no
  lemma DB, stable behavior across the window). `decide` (kernel) where cheap.
- **Only the most ancient, fundamental lemma names** (`mul_comm`,
  `Nat.succ_le_succ`-tier) — never the fresh ones `exact?` prefers.

**Workflow that respects the one-proof constraint:** generate candidates, then
**test-compile against all N `benchmark_versions` as a hard filter**, keep only
survivors, and among survivors pick the shortest/cheapest. The version sweep is
the fitness function, not the current toolchain. Accept a longer proof whenever
the short one compiles on only some versions — that trade is forced, not a
failure. Honest ceiling: **term-mode-defeq + `omega` + stable-core-lemmas,
golfed against the oldest ∩ newest API.**

Dominant move: use search (`exact?`/`apply?`, often after `subst` to kill a
variable) only to *discover* a term, then inline the raw term — but keep it only
if it clears the cross-version filter.

## Metric 1 — Length (`avg_len_pct`, token count)

**Scope:** tokens of the **named theorem's proof body after its defining `:=`**,
not the whole file (comments / blank lines stripped). Nested `have`s count.
Local length uses the **ProofOptimizer lexer** (exact match on all 15 warm-up
`proof_length`s).

**Submission shape (Space clarification):** the row is the benchmark statement
plus a proof — **nothing else**. Forbidden at upload: `sorry`/`admit`/`axiom`,
kernel bypasses, `#count_heartbeats`, and **auxiliary top-level declarations /
syntax extensions** (`def`, `instance`, `attribute`, `macro`, `notation`, …).
Do not outsource into helper `theorem`/`lemma`s either; treat multi-decl
submissions as invalid. Heartbeat refs exist for all 15 problems.

### Tier 1 — free tokens (also cut heartbeats, also version-robust)

- Drop the wrapper: `by exact t` → `t`, `by rfl` → `rfl`.
- Anonymous constructor: `⟨rfl, rfl⟩`, `⟨⟩` for one-constructor goals
  (`And`/`Iff`/structures).
- Dot/projection: `h.1`, `h.2`, `.symm`, `.mp`, `.mpr`, `.elim`, `.trans` —
  chains like `hf.mul hg |>.div hden`.
- Transport `▸`: `rw [h]; exact p` → `h ▸ p`.
- Eta: `fun x ↦ f x` → `f`.
- `nofun`/`nomatch` for impossible cases (safe standalone; can misbehave inside
  a first `|` alternative or `some ⟨…, nofun⟩` positions).
- `rw …; exact` → `rwa`; and reverse-golf `simpa using h` → `exact h` when no
  `simp` actually fires.
- Inline a single-use short `have` — but **never** inline if used ≥3× (inflates
  token count).

### Tier 2 — big single-token collapses (trade against the other two axes)

Use only if you don't also need the heartbeat/robustness thirds. Ranking:
`omega` is safest (algorithmic, deterministic, version-stable — just weak on
`Fin` coercions); bare `simp`/`grind` give the largest collapses but are the
most fragile and heartbeat-heavy.

**Trap:** full term-mode over-golf forces type ascriptions (Lean can't infer
enough). Ascribe only the outermost layer (Kenny Lau), or use
`refine ⟨…, _, …⟩` as the middle ground (Mario).

## Metric 2 — Heartbeats (`avg_hb_pct`)

**Measure right:** `count_heartbeats in <decl>` is a counter delta — raising
`maxHeartbeats` does **not** lower it. "It compiles now because I bumped the
limit" scores zero here. Use `set_option profiler true` + sorry-bisection to
find the hot block.

Ranked cuts (with measured magnitudes from the corpus):

1. **Automation → term/targeted:** `linarith` 730 hb → `sub_pos.mpr h` 279 hb
   (~3×). "Every fast proof is in term mode" (Kenny Lau). Cheap:
   `intro`/`exact`/`apply`/`refine`; expensive: `simp`/`cc`/`decide`/`grind`.
2. **`simp` → `simp only [named]`:** up to ~20× (one lemma 40 s → 2 s) — `simp`
   backtracks over the whole set.
3. **Drop `grind`/`aesop`:** `grind` ≈ 15–20k hb per call; one file went >200k →
   18k after removing `aesop`. "`simp` is by far the most expensive thing."
4. **`decide` → `decide +kernel`** (skips the double elaborator+kernel
   reduction); prefer a direct term/`rfl` when it exists.
5. **Fill stray `_` explicitly** — one underscore fill gave 25× (leaving defeq
   for the elaborator is costly); watch instance diamonds (`synthInstance` cost).

**Validity trap:** `native_decide` is the fastest but adds a compiler-trust
axiom that fails any axiom check. Banned (see below). It still has narrow
*diagnostic* value during exploration only, never in what's submitted: if
`native_decide` closes a goal that plain `decide`/`decide +kernel` can't, that
tells you the goal needs a real computational route the kernel can afford (or
a non-computational proof instead) — treat the discovery as a signal, not a
shortcut.

**Elaborator cost vs. kernel cost are different budgets.** A short term can
still be heartbeat-expensive if the cost is hiding in the elaboration, not the
term itself: a bare `_` the elaborator has to infer, dot-notation resolution,
overloaded-numeral disambiguation, coercion chains, or instance search
(`synthInstance`). Two proofs of the same length can have very different
heartbeat costs for this reason — don't assume shorter implies cheaper.
`Fin`/subtype/cast boundaries are a common place both `omega` and constructor
proofs stall; staying in the native representation across such a boundary
(rather than crossing it early) tends to avoid the stall.

**A tactic-ordering ladder**, roughly cheapest-and-most-durable first, useful
as a search order when golfing a given goal: direct projection/dot-access →
transport or constructor term (`.imp`, `▸`, `⟨_, Ctor args⟩`) → one ancient
stable lemma → `omega` → restricted `simp only [named]` → broader automation
(`grind`/`aesop`/`nlinarith`). Stop descending the ladder as soon as something
compiles and scores well; don't automatically chase the cheapest rung once a
good-enough one is found — the sum objective, not any single axis, is what
counts (see the wrapper's own framing in `prompts/refactor.md`).

**Equality-elimination direction:** `subst` is fine, even preferred, while
exploring — it collapses the goal for you. But leaving the final proof term
built around `subst`-style elimination isn't always the most compact result;
a small oriented `▸` transport at the very end is often shorter once the
right lemma shape is known.

**Automation failures are low-information.** When `simp`/`omega`/`grind` just
fails outright, that tells you little about *why* — prefer diagnosing with
`simp only [...]` on a shrinking lemma set, or `set_option profiler true`,
over guessing at bigger hammers.

*(Source: a direct debrief with the Sol teacher model, 2026-08-25, prompted
with a broader "AI-scale Lean" tips document and Sol's own past winning
episodes. Operational synthesis, not measured against the full corpus the way
the ranked cuts above are — treat with the same "hypothesis, not settled"
caveat as the rest of this document, and note the wrapper prompt Sol actually
receives does *not* include any of this — see the meta-note at the end of
this section.)*

## Recurring golf patterns (evidence from Sol's winning episodes)

Distilled from 5 independent Σ>90 wins across 4 corpora (2026-08-24/25 batch).
Patterns that recurred across *independent* episodes, not single-episode
tricks — see each entry's episode count.

- **Compound-hypothesis transport (3/5 episodes, strongest signal):** once a
  hypothesis or IH is `Or`/`And`/`Exists`-shaped, thread it through with
  `.imp`/`Or.imp`/`And.imp`/`Exists.imp` rather than `cases`-then-reconstruct.
  Shorter, and skips the case-split's `simp_all` bookkeeping. Caution: a term
  built this way can still hide expensive inference behind a `_`  — don't
  assume it's automatically cheap, check the heartbeat number.
- **Term over `grind`/`simp_all`-autofill (2/5, one was the batch's biggest
  single win):** watch for the "pick a disjunct, supply a witness, autofill
  the rest" idiom (`right; exists w; grind` or `simp_all`) — once the
  constructor and its arguments are actually known, a direct term
  `.inr ⟨_, Ctor args⟩` is almost always both shorter and cheaper.
- **Share one tactic across branches:** a single `<;> simp only [named]` (or
  `<;> grind only [named]`) applied once across all case/induction branches,
  rather than a bespoke call repeated per branch. Note this shares *source*
  length, not necessarily heartbeats — it's still one call per goal under the
  hood, and it's fragile if a later edit changes the goal count.
- **`rintro`/`rcases` inline patterns:** `⟨⟩` for structures/exists, `|` for
  sum-type splits — collapses a whole `intro`+`cases`+`obtain` chain into one
  line. Safe and general: this is syntax, not simp-normal-form-dependent, so
  no robustness cost the way `simp`/`rw` chains carry.
- **De-duplicate repeated `have`s:** either extract a small shared combinator
  lemma (when the repeated block is truly identical) or parameterize over the
  varying index (when only one value differs across occurrences). Measure
  before keeping — parameterizing can occasionally *cost* heartbeats if it
  forces the elaborator to re-specialize at each call site.

**Do not generalize:** none of the above ever means importing a *specific*
corpus lemma or constructor name into the wrapper or this doc — the technique
generalizes, the exact library content never does. That would be exactly the
decontamination violation `HANDOFF.md` already warns against.

**Meta-note on all of the above, from both the winning-trace analysis and
Sol's own debrief:** everything in this section and the elaborator-cost notes
above is meant for `STRATEGY.md`/operator use, not for injection into
`prompts/refactor.md` itself. Sol, when asked directly, declined having any
of it (ladder, timeout heuristics, WF-recursion notes) added to its own
wrapper prompt, calling each addition "a plausible new premature-abandonment
trigger" — which matches the existing v1→v4.2 A/B history: v2/v3's more
prescriptive framing scored worse than v4.2's minimal "state the objective,
get out of the way" approach. Keep it that way unless a change is validated
with the same paired-episode A/B method that established the v3 regression,
not adopted by analogy.

## Metric 3 — Robustness (`survival_rate` across `benchmark_versions`)

A full 1/3 of the score, and the one that punishes aggressive golf. Goal:
survive a bump unchanged via low reliance on drifting machinery.

**Avoid (fragility, ranked by evidence):**

- **Non-terminal `simp` / `ring_nf` / `norm_num`** — simp-normal-form drift is
  the #1 silent breaker (Mathlib restates lemmas to the current normal form,
  retroactively breaking `rw`/`simp only` that pinned the old shape).
- **Nondeterministic search** — `nlinarith` (success depends on mvar-id
  numbering, i.e. how many examples precede it in the file), `aesop`,
  `polyrith`. Never leave `exact?`/hammer/`polyrith` invocations in — keep only
  their output term.
- **Defeq-transparency churn** — the 4.33 bump added ~4.5k
  `respectTransparency` set_options across Mathlib; proofs leaning on
  `convert`/`erw`/implicit defeq are the ones that needed band-aids. Prefer
  explicit `rw [lemma]`, spell out instances.
- **Renamed/deprecated names** (`[grind homo]`→`[grind hom]`, module splits) — a
  bare `exact oldName` dies when the alias drops.
- **`autoImplicit`, over-broad `variable`s** — a new `simp` lemma can change
  behavior; explicit binders are durable.

**Prefer:** term-mode `exact <fully-applied term>`, `rfl`/`decide`/`trivial`
(kernel-checked), ancient stable names, terminal automation only (let
`simp`/`omega` *close* the goal so nothing depends on its output shape). For
forward-durability the community is betting on `grind`/`omega` over
`aesop`/`nlinarith`, but `grind` is itself churning fast — for surviving
already-released versions, kernel-honest structural proofs still beat automation.

## Cross-axis map

| Technique | Length | Heartbeats | Robustness | Validity |
|---|---|---|---|---|
| term-mode `exact`/`rfl`/`⟨⟩`/`▸`/dot (Tier 1) | ↓↓ | ↓↓ | ↑↑ (≤3 lines) | ✓ |
| `exact?`-found term, inlined | ↓↓ | ↓↓ | ↑ (pins current names) | ✓ |
| `omega` | ↓ | ~ | ↑ (deterministic) | ✓ |
| bare `simp` / `ring_nf`-then-`rw` | ↓↓ | ↑↑ | ↓↓ | ✓ |
| `grind` / `aesop` | ↓↓ | ↑↑↑ | ↓ (young, churning) | ✓ |
| `simp only [named]` | ↑ (longer) | ↓↓ | ↓ (names rot) | ✓ |
| `decide` (kernel) | ↓ | ↑↑ (can time out) | ↑ | ✓ |
| `native_decide` | ↓ | ↓↓↓ | stable | ✗ adds axiom; can contradict kernel |
| decomposed explicit proof (>3 lines) | ↑↑ (longer) | ↓ | ↑↑ | ✓ |

## Why single-digit-token terms close "semi-hard" goals

Not magic — a lot of library theorems are, after `subst`/defeq, just a
projection or a one-lemma application, and term mode lets you write exactly that:

- `rfl` when the goal reduces by defeq (the hard part is unfolding, done by the
  kernel).
- `⟨⟩` / `⟨rfl, rfl⟩` for structure goals; `nofun` for empty/impossible.
- `.2`, `h.mp`, `h ▸ x`, `‹_›` (anonymous hypothesis by type), `id` — a single
  projection/coercion.
- an `exact?`-found single lemma name inlined as the whole proof (only if it
  survives the version filter).

## Banned constructs — what each is and why

Rejected at upload, before any worker runs: `#eval`, `#reduce`, `IO.*`,
`unsafe`, `extern`, `initialize`, `@[implemented_by]`, `@[extern]`. Two buckets;
the ban closes two holes: running arbitrary code, and letting compiled behavior
diverge from the kernel.

### Bucket A — arbitrary code execution at elaboration/import time (RCE / read the answer key)

- **`#eval`** — runs compiled Lean at elaboration time. An `IO` action evaluated
  here is straight code execution on the worker: read files, hit the network,
  exfiltrate, probe the harness. Not proof content anyway.
- **`IO.*`** — the entire effectful side of the language (filesystem, processes,
  network). Any reachable `IO` is a side effect that could read the expected
  proof or escape the sandbox. Banned wholesale.
- **`initialize`** — an `initialize … ← <IO>` block runs when the module is
  *imported*, so merely loading your file runs arbitrary `IO` (and can register
  environment extensions / mutate global elaborator state). RCE at load time.
- **`#reduce`** — a diagnostic that whnf-reduces and prints an expression. Less a
  security hole than a resource/DoS and probing vector (force pathological
  kernel reduction, inspect internals). Not proof content; cheap to forbid.

### Bucket B — soundness / kernel-bypass escape hatches (fake proofs, native-vs-kernel divergence)

- **`unsafe`** — marks definitions that skip soundness/termination checks
  (`unsafeCast` to coerce any type to any type, unrestricted recursion), from
  which you can manufacture a term of `False` or any goal. A direct route to a
  fake proof.
- **`@[extern "sym"]` / `extern`** — replaces a function's runtime implementation
  with an external C symbol; compiled behavior can differ from the Lean
  definition the kernel checks. The classic "trust the compiler" hole — same
  axiom-scheme risk as `native_decide`, at the definition level.
- **`@[implemented_by f]`** — same divergence, substitute is another Lean def:
  the declaration is `X` while `#eval`/`native_decide` run it as `Y`. Lets native
  evaluation and the kernel disagree — the mechanism behind the "2+2=5" example.

**Unifying rule:** no running code the kernel didn't check, and no making the
compiled world lie to the kernel. It's the definition-level generalization of the
`native_decide` ban — which strongly implies the full harness also does a
`#print axioms`-style axiom-clean check. Assume the Oct 1 full benchmark checks
axioms.

**Practical consequence:** because Bucket B is closed, `decide` is a
kernel-reduced finisher with no `native_decide` escape — so any goal with
nontrivial computation is heartbeat-expensive or times out. That pushes even
decidable goals back toward explicit term/`omega` proofs.

## What the local rig actually measures (Aug 17)

Established by reproducing all 15 reference proofs locally (`verify.py
--measure-references` → `reference_measurements.jsonl`):

- **Heartbeats are measured on the newest toolchain** in a problem's
  `version_info`. `putnam_1964_a4` reproduces at 111474 there against 111476
  published; on v4.25.0 the same proof costs 141082 (+26%). So version choice,
  not machine speed, is what moves the number.
- **Async elaboration silently destroys the measurement.** `IO.getNumHeartbeats`
  is per-thread, so with Lean's parallel elaboration on, the same proof reports
  774 instead of 111474. Every measurement runs under `Elab.async false`.
- **Our numbers run a few percent above published** (typically +0.2% to +3%,
  worst case +18% on the 1.4k-heartbeat CSLib problem, where a constant
  environment-setup cost dominates). The offset is systematic, so reductions are
  scored against the locally-measured reference, not the published one.
- **Reference survival is 100%** where the environment exists: every reference
  proof compiles on every toolchain its row lists. So any failed toolchain in a
  candidate's `compat` is the candidate's fault, not the rig's.

Practical consequence for golfing: the cheapest reliable feedback loop is
`arena.py check` on the newest toolchain (seconds to ~1 min), with
`--all-versions` reserved for confirming a candidate that already looks good.

## Pointers

- Cameron Freer's community golf skill: `cameronfreer/lean4-skills` →
  `proof-golfing.md` + `proof-golfing-patterns.md` (with a `/golf` command and a
  `find_golfable` script).
- **ProofOptimizer** — aimed at exactly this; useful as a baseline or component.
