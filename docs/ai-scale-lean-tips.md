# Lean tips for handling extremely large AI-generated loads

This document attempts to note some Lean tips that are unique to handling
extremely large loads. Some of these are a reverse of common convention, but
as we handle AI-generated loads, we should first address the issue of being
able to effectively build over convention. Still, we attempt to document any
tradeoffs in this doc. This is largely intended for human reading, but just
putting this into an agent's context should be able to help the agents as
well.

## `def`s with `@[irreducible]`

A semireducible `def` (the default) gets unfolded by expensive automation,
typeclass synthesis, `isDefEq`, `simp`, everywhere it appears. `@[irreducible]`
stops that, which helps save time and memory.

Of course, if a later tactic needs to reduce this def, adding this will make
the proof fail. You can still reason about it through its lemmas. The next
section briefs about defs that need to be reduced.

## Write kernel-reduced computations

If a `def` will be reduced by `decide`/`rfl` over data, term-level choices
make the kernel reduce it far faster:

- No `match`, every destructure goes through `.rec` directly.
- No overloaded operators.
- No recursive `def`.

```lean
-- before: `match` compiles to casesOn layers
def sumT (t : Tree) : Int := match t with
  | .leaf        => 0
  | .node l v r  => sumT l + (v + sumT r)

-- after: `.rec` directly (no casesOn layers)
def sumT (t : Tree) : Int :=
  Tree.rec (motive := fun _ => Int) 0
    (fun _l v _r il ir => Int.add il (Int.add v ir)) t
```

This is frequently considered harder to read.

## `decide +kernel`

Plain `decide` reduces the `Decidable` instance in the elaborator. It reduces
twice and more quickly hits `maximum recursion depth` on anything nontrivial.
`decide +kernel` reduces once, in the kernel.

The downside is that this gives much worse diagnostics and fails inelegantly
(can hang and OOM), but if we know that this compiles this is not too much of
an issue. That said, `decide +kernel` can solve some things that `decide` by
itself cannot.

## Prefer structural recursion over well-founded

Well-founded recursion does not reduce definitionally cleanly; the kernel
tries to reduce it and hits deep-recursion / memory blowup.

```lean
-- before: not obviously structural → well-founded recursion, expensive for the kernel
def f (n : Nat) : Nat := <… f (n - 2) …>
termination_by n

-- after: recurse on the constructor (structural) → reduces cleanly, no termination proof
def f : Nat → Nat
  | 0     => <…>
  | 1     => <…>
  | n + 2 => <… f n …>
```

Some recursions are inherently well-founded (such as induction on a group's
order, where a subgroup isn't a structural sub-piece of the type).

## Give explicit types to cut unification / coercion cost

```lean
-- before: expected type unknown → expensive unification/coercion search
def x := someCoercion (f a)

-- after: known expected type → cheap
def x : Target := someCoercion (f a)
```

## Minimize imports

Please stop `import Mathlib` spam. `#min_imports` is your friend.

## Shorten the long pole (multi-file build time)

With enough cores, total build wall-time ≈ the "longest transitive-import
chain weighted by compile time" (we may refer to this as the long pole).
Splitting a heavy file helps only if it moves work into parallel branches;
splitting one file into a chain (each imports the last) is not helpful here.

Find the critical path with `lake exe pole`, the import DAG with
`lake exe graph`. (Proof-body elaboration parallelizes since Lean 4.19.)

## Build `Decidable` instances from a `Bool` function

A derived or tactic-built `Decidable` instance for an inductive predicate
carries `Eq.rec`/`casesOn` layers that only reduce on literal `rfl`, so
`decide` over it is slow. Instead, hand-write a `Bool` version, prove it
equivalent, and build the instance from that.

```lean
-- before: derived / ad-hoc instance for an inductive predicate. Reduces slowly under `decide`
instance : DecidablePred P := <derived or tactic-built>

-- after: Bool version + iff proof, assembled via decidable_of_iff
def Pb (x : α) : Bool := <boolean version>
theorem Pb_iff (x : α) : P x ↔ (Pb x = true) := <proof>
instance : DecidablePred P := fun x => decidable_of_iff _ (Pb_iff x).symm
```

## Untrusted tactics during proving

During the proof process, we may use unsafe methods like `native_decide` in
order to have fast compiling code. We will need to fix this post-hoc, but this
could save a lot of computational time during the proving process.

---

**Note for this repo:** several of these are directly heartbeat-relevant to
the arena's scoring objective (`decide +kernel`, structural-over-well-founded
recursion, `Decidable`-from-`Bool`), but most concern build-time/import-graph
engineering across a whole project — a different axis from single-declaration
proof golfing. `native_decide` specifically is **forbidden** in arena
submissions (see `STRATEGY.md`'s Banned constructs section) — the "fix
post-hoc" caveat matters if this ever gets used as scaffolding during
exploration, since it cannot appear in what's actually submitted.
