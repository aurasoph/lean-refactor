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
  funext x₀
  by_contra hx₀
  have hi : Continuous (fun x => ⟪f x, f x₀⟫_ℝ) :=
    Continuous.inner' f (fun _ => f x₀) hf continuous_const
  have hi₀ : 0 < ⟪f x₀, f x₀⟫_ℝ :=
    real_inner_self_nonneg'.lt_of_ne (Ne.symm (inner_self_eq_zero'.not.mpr hx₀))
  obtain ⟨r, hr, hi_pos⟩ := Metric.eventually_nhds_iff_ball.mp
    (continuousAt_const.eventually_lt hi.continuousAt hi₀)
  let φ : ContDiffBump x₀ := ⟨r / 2, r, by positivity, by linarith⟩
  have hφ : IsTestFunction φ := ⟨φ.contDiff, φ.hasCompactSupport⟩
  have hsupport : Function.support (fun x => φ x * ⟪f x, f x₀⟫_ℝ) =
      Metric.ball x₀ r := by
    rw [Function.support_mul, φ.support_eq, Set.inter_eq_left]
    exact fun x hx => (hi_pos x hx).ne'
  have hnonneg : ∀ x, 0 ≤ φ x * ⟪f x, f x₀⟫_ℝ := by
    intro x
    by_cases hx : x ∈ Function.support φ
    · exact mul_nonneg φ.nonneg (hi_pos x (φ.support_eq ▸ hx)).le
    · simp [Function.notMem_support.mp hx]
  have hint : Integrable (fun x => φ x * ⟪f x, f x₀⟫_ℝ) μ :=
    (hφ.smooth.continuous.mul hi).integrable_of_hasCompactSupport
      hφ.supp.mul_right
  have hpos : 0 < ∫ x, φ x * ⟪f x, f x₀⟫_ℝ ∂μ :=
    (integral_pos_iff_support_of_nonneg hnonneg hint).2 (by
      rw [hsupport]
      exact Metric.isOpen_ball.measure_pos μ (Metric.nonempty_ball.mpr hr))
  have := hg (fun x => φ x • f x₀) (IsTestFunction.smul_right hφ contDiff_const)
  simp only [inner_smul_right'] at this
  exact hpos.ne' this
