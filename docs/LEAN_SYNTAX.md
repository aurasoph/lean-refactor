# Lean 4 base-library syntax inventory (exhaustive scan)

**Toolchain:** `leanprover/lean4:v4.32.0`  
**Question answered:** did we look over literally every `.lean` in the base library?

## Methodology (honest)

| Scope | Files | What we did |
|---|---|---|
| `Init/**/*.lean` | 600 | Full text scan for `notation` / `infix*` / `prefix` / `postfix` / `syntax` / `macro` / `macro_rules` / `declare_syntax_cat` / `binder_predicate` |
| `Std/**/*.lean` | 475 | Same |
| **Total** | **1075** | Every file opened |

**Finding:** only **78 / 1075** files *define* any syntax/macro/notation. The other **997** are lemmas, instances, proofs, and docs — they *use* sugar, they don’t add it.

Raw match dump (1139 definition lines): `_syntax_raw_hits.txt` next to this file.

**Also included below:** `Lean/Parser/**` builtin parsers. Those are the *language* surface (not Init/Std library), but without them the inventory of “what you can write” is incomplete (`⟨⟩`, `by`, `fun`, `do`, … live there).

**Not included:** Mathlib / Batteries / Lake package extras.

---

## 0. The `_ * _` elaborator trick (kept from earlier)

Holes `_` + **implicit lambdas** + expected pi-type:

```lean
example : Nat → Nat → Nat := _ * _     -- ≈ fun a b => a * b
example : P → Q → P ∧ Q := ⟨_, _⟩      -- ≈ fun hp hq => ⟨hp, hq⟩
example : Nat → Nat → Nat := (· * ·)  -- explicit cdot form
```

`‹T›` / `‹_›` = `show T by assumption` / `by assumption`.

---

## 1. Files that actually define syntax (complete list, 78)

### Init (62)

```
Init/BinderPredicates.lean
Init/ByCases.lean
Init/CbvSimproc.lean
Init/Coe.lean
Init/Control/Basic.lean
Init/Conv.lean
Init/Core.lean
Init/Data/Array/Basic.lean
Init/Data/Array/Mem.lean
Init/Data/Array/Subarray.lean
Init/Data/BitVec/Basic.lean
Init/Data/Bool.lean
Init/Data/Format/Macro.lean
Init/Data/Iterators/Basic.lean
Init/Data/List/Basic.lean
Init/Data/List/BasicAux.lean
Init/Data/List/Notation.lean
Init/Data/Option/Basic.lean
Init/Data/Ord/Basic.lean
Init/Data/Range/Basic.lean
Init/Data/Range/Polymorphic/Basic.lean
Init/Data/Range/Polymorphic/GetElemTactic.lean
Init/Data/Range/Polymorphic/PRange.lean
Init/Data/Repr.lean
Init/Data/SInt/Bitwise.lean
Init/Data/SInt/Lemmas.lean
Init/Data/Slice/Notation.lean
Init/Data/String/Iterator.lean
Init/Data/String/Pattern/Basic.lean
Init/Data/String/Slice.lean
Init/Data/String/Substring.lean
Init/Data/String/Termination.lean
Init/Data/ToString/Macro.lean
Init/Data/UInt/Bitwise.lean
Init/Data/UInt/Lemmas.lean
Init/Data/Vector/Basic.lean
Init/Ext.lean
Init/GetElem.lean
Init/Grind/Annotated.lean
Init/Grind/Attr.lean
Init/Grind/Interactive.lean
Init/Grind/Lint.lean
Init/Grind/Propagator.lean
Init/Grind/Tactics.lean
Init/Guard.lean
Init/LawfulBEqTactics.lean
Init/MacroTrace.lean
Init/Meta.lean
Init/Meta/Defs.lean
Init/Notation.lean
Init/NotationExtra.lean
Init/Prelude.lean
Init/RCases.lean
Init/SimpLemmas.lean
Init/Simproc.lean
Init/Sym/DSimp/DSimprocDSL.lean
Init/Sym/Simp/SimprocDSL.lean
Init/System/IO.lean
Init/Tactics.lean
Init/TacticsExtra.lean
Init/Try.lean
Init/WFTactics.lean
```

### Std (16)

```
Std/Data/DHashMap/Internal/RawLemmas.lean
Std/Data/DHashMap/RawLemmas.lean
Std/Data/DTreeMap/Internal/Lemmas.lean
Std/Do/PostCond.lean
Std/Do/SPred/Notation.lean
Std/Do/SPred/Notation/Basic.lean
Std/Do/WP/Basic.lean
Std/Internal/Do/ExceptPost.lean
Std/Internal/Do/Triple/Basic.lean
Std/Sat/AIG/Basic.lean
Std/Tactic/BVDecide/Syntax.lean
Std/Tactic/Do/ProofMode.lean
Std/Tactic/Do/Syntax.lean
Std/Time/Format.lean
Std/Time/Notation.lean
Std/Time/Notation/Spec.lean
```

*(A few Std Data `~m` Equiv infixes also appear in HashMap/TreeMap Basic/Raw files — captured in §2.)*

---

## 2. Every Init/Std infix / prefix / postfix / real notation

Deduped by operator string. ASCII alts noted.

### Logic / equality / order / sets

| Op | Kind | Target | Where |
|---|---|---|---|
| `↔` / `<->` | infix 20 | `Iff` | Core |
| `∧` / `/\` | infixr 35 | `And` | Notation |
| `∨` / `\/` | infixr 30 | `Or` | Notation |
| `¬` | notation max | `Not` | Notation |
| `=` | infix 50 | `Eq` | Notation |
| `≠` | infix 50 | `Ne` | Core |
| `==` | infix 50 | `BEq.beq` | Notation |
| `!=` | infix 50 | `bne` | Core |
| `≍` | infix 50 | `HEq` | Notation |
| `≈` | infix 50 | `HasEquiv.Equiv` | Core |
| `≤` / `<=` | infix 50 | `LE.le` | Notation |
| `<` | infix 50 | `LT.lt` | Notation |
| `≥` / `>=` | infix 50 | `GE.ge` | Notation |
| `>` | infix 50 | `GT.gt` | Notation |
| `∈` | notation 50 | `Membership.mem` | Notation |
| `∉` | notation 50 | `¬(· ∈ ·)` | Notation |
| `⊆` `⊂` `⊇` `⊃` | infix 50 | Subset family | Core |
| `∪` | infixl 65 | `Union.union` | Core |
| `∩` | infixl 70 | `Inter.inter` | Core |
| `\\` | infix 70 | `SDiff.sdiff` | Core |
| `∅` / `{}` | notation | `EmptyCollection.emptyCollection` | Core |
| `⊕` / `⊕'` | infixr 30 | `Sum` / `PSum` | Core |
| `⊑` | infix 50 | `PartialOrder.rel` | Internal.Order |
| `⊥` | notation | `bot` | Internal.Order |
| `⊤` | notation | `top` | Std Do Order |
| `⊓` `⊔` | infixl | meet / join | Std Do Order |
| `⇨` | infixr 60 | `himp` | Std Do Frame |

### Arithmetic / bits / algebra ops

| Op | Kind | Target |
|---|---|---|
| `+` `-` `*` `/` `%` `^` `++` | HAdd/HSub/HMul/HDiv/HMod/HPow/HAppend | Notation |
| `•` | HSMul | Notation |
| `-` (prefix) | Neg | Notation |
| `⁻¹` (postfix) | Inv | Notation |
| `|||` `^^^` `&&&` `<<<` `>>>` `~~~` | bitwise HOr/HXor/HAnd/shifts/Complement | Notation |
| `∣` | Dvd | Notation |
| `∘` | Function.comp | Notation |
| `×` / `×'` | Prod / PProd | Notation |
| `/.` | Rat.divInt | Data.Rat |
| `^^` | Bool xor | Data.Bool |
| `-[n+1]` | Int.negSucc | Data.Int |

### List / array / perm

| Op | Target |
|---|---|
| `::` | List.cons |
| `<+` `<+:` `<:+` `<:+:` | Sublist / IsPrefix / IsSuffix / IsInfix |
| `~` | Perm (List/Array/Vector) |
| `~m` | map/set Equiv (Std Hash*/Tree*) |

### Functor / monad / control

| Op | Target |
|---|---|
| `<$>` `<&>` | Functor.map / mapRev |
| `>>=` `=<<` `>=>` `<=<` | Bind family |
| `<|>` `>>` `<*>` `<*` `*>` | OrElse / AndThen / Seq* |
| `<&&>` `<||>` | andM / orM |

### Std Do / verification / SAT (specialized)

| Op | Meaning |
|---|---|
| `∧ₑ` `→ₑ` `⊢ₑ` | ExceptConds |
| `∧ₚ` `→ₚ` `⊢ₚ` | PostCond |
| `⦃ pre ⦄ x ⦃ post ⦄` | Hoare triple |
| `⌜p⌝` | embed Prop into lattice / SPred |
| `⊢ₛ` `⊣⊢ₛ` `spred(·)` `term(·)` | SPred proof mode |
| `wp⟦e⟧` | weakest precondition |
| `EPost⟨…⟩` / `epost⟨…⟩` | exception postconditions |
| `⊨` `⊭` | BVDecide Entails |
| `⟦aig, …⟧` | AIG entrypoint notation |

### Time (Std)

`zoned("…")` `datetime("…")` `date("…")` `time("…")` `offset("…")` `timezone("…")` `datespec("…")`

---

## 3. Term sugar defined in Init/Std (beyond infix)

### GetElem (`Init/GetElem.lean`)

| Syntax | Meaning |
|---|---|
| `a[i]` | `getElem` + `get_elem_tactic` proof |
| `a[i]'h` | `getElem` with explicit proof `h` |
| `a[i]?` | `getElem?` |
| `a[i]!` | `getElem!` (panic on fail) |

### Collections / ranges / slices

| Syntax | File |
|---|---|
| `#[a, b, …]` | Array |
| `#v[a, b, …]` | Vector |
| `[a, b, …]` | List |
| `%[a, b \| d]` | List with default (decidable) |
| `a[i:j]` `a[i:]` `a[:j]` | Array Subarray |
| `[:n]` `[i:j]` `[:n:s]` `[i:j:s]` | Range.Basic |
| `a...*` `*...*` `a<...*` `a...<b` `a...b` `*...<b` `*...b` `a<...<b` `a<...b` `a...=b` `*...=b` `a<...=b` | Polymorphic PRange |
| `{a, b}` | NotationExtra singleton/set-ish `{…}` |
| `{ x // p }` / `{ x : α // p }` | Subtype (Notation) |

### BitVec / numerics / strings / format

| Syntax | Meaning |
|---|---|
| `8#n` / `n#'w` | BitVec width literals |
| `nat_lit n` | raw nat literal |
| `s!"…"` `f!"…"` `println! …` | interpolators |
| `↑` `⇑` `↥` | Coe / CoeFun / CoeSort |

### Binder predicates (`Init/BinderPredicates.lean`)

```lean
∃ x < 2, p x     -- ∃ x, x < 2 ∧ p x
∀ x ∈ s, p x     -- ∀ x, x ∈ s → p x
```

Registered preds: `> ≥ < ≤ ≠ ∈ ∉ ⊆ ⊂ ⊇ ⊃`.

### Calc / exists / sigma macros (`NotationExtra`)

| Syntax | Meaning |
|---|---|
| `calc …` | calculational proof (term + tactic + conv) |
| `∃` / `exists` binders | `Exists` |
| `Σ` / `Σ'` binders | Sigma / PSigma |
| `(x : α) × β` | dependent Sigma via × |
| `e matches p \| q` | term-level matches |
| `funext …` | tactic macro |

### Assumption / cast / pipelines (Init)

| Syntax | Meaning |
|---|---|
| `‹T›` / `‹_›` | assumption-by-type |
| `exact?%` | term form of exact? |
| `mod_cast e` | cast normalization as term |
| `e <| f` `e \|> f` `f $ e` | pipelines |
| `by_elab …` | elaborator metaprogram as term |
| `without_expected_type e` | ignore expected type |
| `include_str "path"` | embed file contents |
| `if` / `if h :` / `if let` / `bif` | ite / dite / match / cond |

---

## 4. Declared syntax categories (Init/Std)

```
conv
rawStx
binderPred
rcasesPat  rintroPat
sym_simproc  sym_discharger  sym_simp_field
sym_dsimproc  sym_dsimp_field
grind_filter  grind  grind_ref
mcasesPat  mrefinePat  mintroPat  mrevertPat   (Std Do)
```

Plus grind interactive tactics use category `grind` (own mini-language).

---

## 5. Complete Init/Std tactic & conv keyword inventory (~243)

Alphabetized. Includes macros that register as tactics. Conv-mode keywords mixed in where they share the tactic/conv syntax scan.

```
!  ( )  *  .  :  :=  =>  ?  [ ]  |
·  ∀  ∎

ac_nf0  ac_rfl  admit
all_goals  and_intros  any_goals
apply  apply?  apply_assumption  apply_ext_theorem  apply_rfl  apply_rules
arg  array_get_dec  array_mem_dec  as_aux_lemma  assumption
at  attempt_all  attempt_all_par
bv_check  bv_decide  bv_decide?  bv_normalize  bv_omega
by  by_cases
calc  case  case'  cases  cbv  change  classical  clean_wf
clear  clear_value  congr  constructor  contradiction
conv  conv'  cutsat
dbg_trace  decide  decide_cbv
decreasing_tactic  decreasing_trivial  decreasing_trivial_pre_omega
delta  deriving_LawfulEq_tactic  deriving_LawfulEq_tactic_step  deriving_ReflEq_tactic
done  dsimp  dsimp?
else  empty  enter  eq_refl  exact  exact?  exfalso  expose_names  ext  extract_lets
fail  fail_if_success  false_or_by_contra  first  first_par  focus
fun  fun_cases  fun_induction  funext
generalize  generalizing
get_elem_tactic  get_elem_tactic_extensible  get_elem_tactic_trivial
grind  grind?  grind_linarith  grind_order  grobner
guard_expr  guard_hyp  guard_target
have
if  impossible  in  induction  infer_instance  injection  injections  intro  intros  iterate
left  let  let rec  let_to_have  lhs  lia  lift_lets
massumption  mcases  mclear  mconstructor  mdup  mexact  mexfalso  mexists
mframe  mhave  mintro  mleave  mleft  monotonicity
mpure  mpure_intro  mrefine  mrename_i  mreplace  mrevert  mright
mspec  mspec_no_bind  mspecialize  mspecialize_pure  mstart  mstop
mvcgen  mvcgen'  mvcgen?  mvcgen_trivial  mvcgen_trivial_extensible
my_trivial
native_decide  nofun  nomatch   (nomatch also via macro)
norm_cast  norm_cast0
obtain  omega  only  order
pattern  push_cast
rcases  rcases?  rec  reduce  refine  refine'  rename  rename_i
repeat  repeat'  repeat1'  replace  revert  rewrite  rfl  rfl'  rhs  right
rintro  rintro?  rotate_left  rotate_right  run_tac  rw?  rw_mod_cast  rwa (macro)
show  show_term
simp  simp?  simp_all  simp_all?  simp_all_arith  simp_all_arith!
simp_arith  simp_arith!  simp_match  simp_to_model  simp_to_raw  simp_wf  simpa
simplifying_assumptions  sizeOf_list_dec  skip  sleep  solve  solve_by_elim  sorry
specialize  split  subst  subst_eqs  subst_vars  suggestions  sym  symm  symm_saturate
tactic  tactic'  then  trace  trace_state  tree_tac  trivial  try?  try_suggestions
unfold  until  using  using!
wf_trivial  whnf  with  with_annotate_state
with_reducible  with_reducible_and_instances  with_unfolding_all  with_unfolding_none
zeta
```

Also from TacticsExtra / Notation macros (may not all appear as leading `"…"`):  
`rwa`, `exact_mod_cast`, `apply_mod_cast`, `assumption_mod_cast`, `simpa`, `iterate`, …

### Conv-focused (also in Init/Conv.lean)

Typical: `lhs` `rhs` `arg` `ext` `enter` `pattern` `whnf` `zeta` `delta` `unfold` `change` `equals`/`congr` variants, `at`/`in` location, nested `tactic` / `conv'`.

### Grind mini-language (`Init/Grind/Interactive.lean`)

Own category `grind` with `·`, `<;>`, `try`, `admit`, `exact`, filters, etc. — a tactic DSL inside `grind`.

### Sym/simproc DSLs

`Init/Sym/Simp/SimprocDSL.lean`, `Init/Sym/DSimp/DSimprocDSL.lean`, `Init/Simproc.lean`, `Init/CbvSimproc.lean`: commands like `simproc` / `dsimproc` and field syntax for declaring simplification procedures.

---

## 6. Command-level sugar in Init/Std (selected)

| Command-ish | Role |
|---|---|
| `simproc` / `dsimproc` | declare simp procedures |
| `run_cmd` / `run_elab` / `run_meta` | run elaborator code |
| `#reduce` | reduce command |
| `#guard_msgs` | test message output |
| `unif_hint` | unification hints |
| `class_abbrev` | class abbreviation |
| `declare_*_theorems` macros | UInt/SInt bulk lemma gens |
| Time/format commands | Std.Time |

(Plus attributes registered as `:attr` syntax — grind attrs, deprecated, coe, suggest_for, univ_out_params, command_code_action, … mostly in `Init/Notation.lean` / `Init/Grind/Attr.lean`.)

---

## 7. Language builtins (`Lean/Parser/**`) — not Init, but required

These are C++/Lean *parser* builtins. They are why `⟨⟩`, `by`, `fun`, `do` exist even with an empty Init.

### Term parsers (`Lean/Parser/Term.lean` + Basic)

`by`/`byTactic`, `ident`, `num`, `scientific`, `str`, `char`, `Type`/`Sort`/`Prop`, `sorry`, `·` (cdot), `(e : τ)`, `(a,b)`, `(e)`, `⟨…⟩`, `suffices`, `show`, `@`, `.(e)`, dependent `→`, `∀`, `match`, `nomatch`, `nofun`, `{ struct }`, `fun`/`λ`, `let`/`have`/`let_fun`/`let_delayed`/`haveI`/`letI`, `let rec`, `where`, `unsafe`, `app`, `.field` / `.1`, `→`, `.ident`, `.{u}`, `x@pat`, `\|>.field`, `▸`, `panic!`, `unreachable!`, `dbg_trace`, `assert!`, `match_expr`/`let_expr`, `decl_name%`, `infer_instance`/`inferInstanceAs`, holes `_` / `?m`, binders `( ) { } ⦃ ⦄ [ ]`, …

### Commands (`Lean/Parser/Command.lean`)

`def`/`theorem`/`lemma`/`example`/`abbrev`/`inductive`/`structure`/`class`/`instance`/`axiom`, `section`/`namespace`/`end`, `variable`/`universe`, `#check`/`#eval`/`#print`/`#print axioms`/…, `set_option`, `attribute`, `export`/`import`/`open`, `mutual`, `initialize`, `deriving`, `include`/`omit`, `recommended_spelling`, …

### Do notation (`Lean/Parser/Do.lean`)

`do`, `let`/`←`/`←` variants, `have`, `if`/`unless`/`for`/`match`/`try`, `break`/`continue`/`return`, `repeat`/`while`, `assert!`, …

### Tactic parser scaffolding

`Lean/Parser/Tactic.lean`, `Term/Basic.lean` tacticSeq forms — Init then *fills* them with the keywords in §5.

---

## 8. What the other 997 `.lean` files are

Not syntax. Typical contents:

- Lemma/theorem statements and proofs (often *using* the sugar above densely — see `Init/PropLemmas.lean`)
- Typeclass instances
- `@[simp]` / `@[grind]` / `@[inline]` attributes on ordinary defs
- Docs

So “read every file” ≠ “every file adds syntax.” The syntax surface of the base library is concentrated in the 78 files listed in §1, plus `Lean/Parser`.

---

## 9. Arena-relevant subset (short)

For term-mode golf that survives versions, the high-value core is:

**Language:** `⟨⟩` `·` `_` implicit-lambdas `▸` `.1/.2` `.mp` `‹_›` `nofun`/`nomatch` `rfl` `id` `show`/`have`/`fun`  
**Init ops:** `∧∨¬=↔` projections, `calc`  
**Avoid for robustness:** `exact?`, bare `simp`, `grind`/`aesop`, `native_decide`, library-fresh names  

See also `STRATEGY.md`.

---

## 10. Regeneration

To re-scan after a toolchain bump:

```bash
# from repo root; adjust toolchain path
python3 -c "..."  # or re-run the extraction used to build _syntax_raw_hits.txt
```

This document was generated from a full pass over **all 1075** Init+Std `.lean` files on **v4.32.0**, not a hand-picked sample.
