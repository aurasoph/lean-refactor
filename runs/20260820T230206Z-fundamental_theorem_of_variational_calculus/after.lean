/-
Copyright (c) 2025 Tomas Skrivan. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Tomas Skrivan, Joseph Tooby-Smith
-/
module

public import Physlib.Mathematics.VariationalCalculus.IsTestFunction
public import Mathlib.Analysis.Calculus.BumpFunction.InnerProduct
/-!

# Fundamental lemma of the calculus of variations

The key took in variational calculus is:
```
∀ h, ∫ x, f x * h x = 0 → f = 0
```
which allows use to go from reasoning about integrals to reasoning about functions.

## Overview of variational calculus

The variational calculus API in Physlib is designed to match and formalize the physicists intuition
of variational calculus. It is not designed to be a general API for variational calculus.

Within variational caclulus we are interested in function transformations, `F : (X → U) → (Y → V)`.
In physics this functional is often of the form `L : (Time → U) → Time → ℝ`,
which represents the Lagrangian of a system. We will use this to explain the formalization
within this API.

The action is nominally given by
$$S[u] = \int L(u, t) dt,$$
however it is convenient to
introduce another function `φ` and define the action as
$$S[u] = \int φ(t) L(u, t) dt.$$
In the end we will set `φ := fun _ => 1`.

We now consider $$\frac{\partial}{\partial s} S[u + s * \delta u]$$ at `s = 0`,
which is the variational derivative of `S` at `u` in the direction `δu`.
This is equal to
$$
\int φ(t) * \left. \frac{\partial}{\partial s} L(u + s * \delta u, t)\right|_{s = 0}dt
$$
Let us denote the function
$$
\delta u,\, t \mapsto \left. \frac{\partial}{\partial s} L(u + s * \delta u, t)\right|_{s = 0}
$$ as `Lᵤ : (Time → U) → (Time → ℝ)`.
Then the variational derivative is
$$\int φ (t) Lᵤ(δu, t) dt.$$

It may then be possible to find a function `Gᵤ : (Time → ℝ) → Time → U`
such that
$$
\int φ(t) Lᵤ(δu, t) dt = \int \langle Gᵤ(φ, t), δu(t)\rangle dt
$$
This is usually done by integration by parts.

We now set `φ := fun _ => 1` and get `grad u := Gᵤ (fun _ => 1)`, which is the
variational gradient at `u`. The Euler–Lagrange equations, for example, are then `grad u = 0`.

In our API, the relationship between
- `Lᵤ` and `Gᵤ` is captured by the `HasVarAdjoint`.
- `L` and `Gᵤ` by `HasVarAdjDeriv`.
- `L` and `grad u` by `HasVarGradientAt`.

In practice we assume that `L` has a certain locality property
`IsLocalizedFunctionTransform`, which allows us to work with functions
`φ` and `δu` which have compact support.

This API assumes that `U` is an inner-product space. This can be considered as the full
configuration space, or a local chart thereof.

## References

- https://leanprover.zulipchat.com/#narrow/channel/479953-Physlib/topic/Variational.20Calculus/with/529022834

-/

@[expose] public section

open MeasureTheory InnerProductSpace InnerProductSpace'

variable
  {X} [NormedAddCommGroup X] [NormedSpace ℝ X] [MeasurableSpace X]
  {V} [NormedAddCommGroup V] [NormedSpace ℝ V] [InnerProductSpace' ℝ V]
  {Y} [NormedAddCommGroup Y] [InnerProductSpace ℝ Y] [FiniteDimensional ℝ Y][MeasurableSpace Y]


lemma fundamental_theorem_of_variational_calculus' {f : Y → V}
    (μ : Measure Y) [IsFiniteMeasureOnCompacts μ] [μ.IsOpenPosMeasure]
    [OpensMeasurableSpace Y]
    (hf : Continuous f) (hg : ∀ g, IsTestFunction g → ∫ x, ⟪f x, g x⟫_ℝ ∂μ = 0) :
    f = 0 := by
  apply funext
  intro x₀
  by_contra hx₀
  let q : Y → ℝ := fun x => ⟪f x, f x₀⟫_ℝ
  have hp : 0 < q x₀ :=
    lt_of_le_of_ne real_inner_self_nonneg' (Ne.symm (inner_self_eq_zero'.not.mpr hx₀))
  have hc : Continuous q :=
    Continuous.inner' f (fun _ => f x₀) hf continuous_const
  obtain ⟨δ, hδ, hball⟩ := Metric.isOpen_iff.mp (isOpen_Ioi.preimage hc) x₀ hp
  haveI : HasContDiffBump Y := hasContDiffBump_of_innerProductSpace Y
  let φ : ContDiffBump x₀ := ⟨δ / 2, δ, half_pos hδ, half_lt_self hδ⟩
  have hsupp : Function.support (fun x => φ x * q x) =
      Metric.ball x₀ δ := by
    rw [Function.support_mul, φ.support_eq]
    exact Set.inter_eq_left.mpr fun x hx => (hball hx).ne'
  have hi : Integrable (fun x => φ x * q x) μ :=
    (φ.continuous.mul hc).integrable_of_hasCompactSupport
      φ.hasCompactSupport.mul_right
  have hn : ∀ x, 0 ≤ φ x * q x := by
    intro x
    by_cases hx : x ∈ Metric.ball x₀ δ
    · exact mul_nonneg φ.nonneg (hball hx).le
    · rw [← φ.support_eq] at hx
      rw [Function.notMem_support.mp hx, zero_mul]
  have hpos : 0 < ∫ x, φ x * q x ∂μ :=
    (integral_pos_iff_support_of_nonneg hn hi).2
      (hsupp.symm ▸ Metric.measure_ball_pos μ x₀ hδ)
  exact hpos.ne' (by simpa only [q, inner_smul_right'] using
    (hg (fun x => φ x • f x₀)
      (IsTestFunction.smul_right ⟨φ.contDiff, φ.hasCompactSupport⟩ contDiff_const)))
