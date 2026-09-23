/-
Copyright (c) 2025 Joseph Tooby-Smith. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Joseph Tooby-Smith
-/
module

public import Physlib.QFT.PerturbationTheory.WickAlgebra.SuperCommute
public import Physlib.QFT.PerturbationTheory.FieldOpFreeAlgebra.TimeOrder
/-!

# Time Ordering on Field operator algebra

-/

@[expose] public section

namespace FieldSpecification
open Module FieldOpFreeAlgebra
open Physlib.List
open FieldStatistic

namespace WickAlgebra
variable {𝓕 : FieldSpecification}

lemma ι_timeOrderF_superCommuteF_superCommuteF_eq_time_ofCrAnListF {φ1 φ2 φ3 : 𝓕.CrAnFieldOp}
    (φs1 φs2 : List 𝓕.CrAnFieldOp) (h :
      crAnTimeOrderRel φ1 φ2 ∧ crAnTimeOrderRel φ1 φ3 ∧
      crAnTimeOrderRel φ2 φ1 ∧ crAnTimeOrderRel φ2 φ3 ∧
      crAnTimeOrderRel φ3 φ1 ∧ crAnTimeOrderRel φ3 φ2) :
    ι 𝓣ᶠ(ofCrAnListF φs1 * [ofCrAnOpF φ1, [ofCrAnOpF φ2, ofCrAnOpF φ3]ₛF]ₛF *
    ofCrAnListF φs2) = 0 := by
  calc _
      _ = ι (𝓣ᶠ(ofCrAnListF (φs1 ++ φ1 :: φ2 :: φ3 :: φs2))) -
          𝓢(𝓕.crAnStatistics φ1, (ofList 𝓕.crAnStatistics [φ2, φ3])) •
          ι (𝓣ᶠ(ofCrAnListF (φs1 ++ φ2 :: φ3 :: φ1 :: φs2))) -
          𝓢(𝓕.crAnStatistics φ2, 𝓕.crAnStatistics φ3) •
          (ι (𝓣ᶠ(ofCrAnListF (φs1 ++ φ1 :: φ3 :: φ2 :: φs2))) -
          𝓢(𝓕.crAnStatistics φ1, ofList 𝓕.crAnStatistics [φ3, φ2]) •
          ι 𝓣ᶠ(ofCrAnListF (φs1 ++ φ3 :: φ2 :: φ1 :: φs2))) := by
        rw [← ofCrAnListF_singleton, ← ofCrAnListF_singleton, ← ofCrAnListF_singleton]
        rw [superCommuteF_ofCrAnListF_ofCrAnListF]
        simp only [List.singleton_append, ofList_singleton, map_sub, map_smul]
        rw [superCommuteF_ofCrAnListF_ofCrAnListF, superCommuteF_ofCrAnListF_ofCrAnListF]
        simp only [List.cons_append, List.nil_append, ofList_singleton, mul_sub, ←
          ofCrAnListF_append, Algebra.mul_smul_comm, sub_mul, List.append_assoc,
          Algebra.smul_mul_assoc, map_sub, map_smul]
  let l1 :=
    (List.takeWhile (fun c => ¬ crAnTimeOrderRel φ1 c)
    ((φs1 ++ φs2).insertionSort crAnTimeOrderRel))
    ++ (List.filter (fun c => crAnTimeOrderRel φ1 c ∧ crAnTimeOrderRel c φ1) φs1)
  let l2 := (List.filter (fun c => crAnTimeOrderRel φ1 c ∧ crAnTimeOrderRel c φ1) φs2)
    ++ (List.filter (fun c => crAnTimeOrderRel φ1 c ∧ ¬ crAnTimeOrderRel c φ1)
    ((φs1 ++ φs2).insertionSort crAnTimeOrderRel))
  have h123 : ι 𝓣ᶠ(ofCrAnListF (φs1 ++ φ1 :: φ2 :: φ3 :: φs2)) =
      crAnTimeOrderSign (φs1 ++ φ1 :: φ2 :: φ3 :: φs2)
      • (ι (ofCrAnListF l1) * ι (ofCrAnListF [φ1, φ2, φ3]) * ι (ofCrAnListF l2)) := by
    have h1 := insertionSort_of_eq_list 𝓕.crAnTimeOrderRel φ1 φs1 [φ1, φ2, φ3] φs2
      (by simp_all)
    rw [timeOrderF_ofCrAnListF, show φs1 ++ φ1 :: φ2 :: φ3 :: φs2 = φs1 ++ [φ1, φ2, φ3] ++ φs2
      by simp, crAnTimeOrderList, h1]
    simp only [List.append_assoc, decide_not,
      Bool.decide_and, ofCrAnListF_append, map_smul, map_mul, l1, l2, mul_assoc]
  have h132 : ι 𝓣ᶠ(ofCrAnListF (φs1 ++ φ1 :: φ3 :: φ2 :: φs2)) =
      crAnTimeOrderSign (φs1 ++ φ1 :: φ2 :: φ3 :: φs2)
      • (ι (ofCrAnListF l1) * ι (ofCrAnListF [φ1, φ3, φ2]) * ι (ofCrAnListF l2)) := by
    have h1 := insertionSort_of_eq_list 𝓕.crAnTimeOrderRel φ1 φs1 [φ1, φ3, φ2] φs2
        (by simp_all)
    rw [timeOrderF_ofCrAnListF, show φs1 ++ φ1 :: φ3 :: φ2 :: φs2 = φs1 ++ [φ1, φ3, φ2] ++ φs2
      by simp, crAnTimeOrderList, h1]
    simp only [decide_not,
      Bool.decide_and, ofCrAnListF_append, map_smul, map_mul, l1, l2, mul_assoc]
    congr 1
    have hp : List.Perm [φ1, φ3, φ2] [φ1, φ2, φ3] := .cons φ1 (.swap φ2 φ3 [])
    rw [crAnTimeOrderSign, Wick.koszulSign_perm_eq _ _ φ1 _ _ _ _ _ hp, ← crAnTimeOrderSign]
    · simp
    · simp_all
  have hp231 : List.Perm [φ2, φ3, φ1] [φ1, φ2, φ3] :=
    ((List.Perm.swap φ1 φ3 []).cons φ2).trans (List.Perm.swap φ1 φ2 [φ3])
  have h231 : ι 𝓣ᶠ(ofCrAnListF (φs1 ++ φ2 :: φ3 :: φ1 :: φs2)) =
      crAnTimeOrderSign (φs1 ++ φ1 :: φ2 :: φ3 :: φs2)
      • (ι (ofCrAnListF l1) * ι (ofCrAnListF [φ2, φ3, φ1]) * ι (ofCrAnListF l2)) := by
    have h1 := insertionSort_of_eq_list 𝓕.crAnTimeOrderRel φ1 φs1 [φ2, φ3, φ1] φs2
        (by simp_all)
    rw [timeOrderF_ofCrAnListF, show φs1 ++ φ2 :: φ3 :: φ1 :: φs2 = φs1 ++ [φ2, φ3, φ1] ++ φs2
      by simp, crAnTimeOrderList, h1]
    simp only [decide_not,
      Bool.decide_and, ofCrAnListF_append, map_smul, map_mul, l1, l2, mul_assoc]
    congr 1
    rw [crAnTimeOrderSign, Wick.koszulSign_perm_eq _ _ φ1 _ _ _ _ _ hp231, ← crAnTimeOrderSign]
    · simp
    · simp_all
  have h321 : ι 𝓣ᶠ(ofCrAnListF (φs1 ++ φ3 :: φ2 :: φ1 :: φs2)) =
      crAnTimeOrderSign (φs1 ++ φ1 :: φ2 :: φ3 :: φs2)
      • (ι (ofCrAnListF l1) * ι (ofCrAnListF [φ3, φ2, φ1]) * ι (ofCrAnListF l2)) := by
    have h1 := insertionSort_of_eq_list 𝓕.crAnTimeOrderRel φ1 φs1 [φ3, φ2, φ1] φs2
        (by simp_all)
    rw [timeOrderF_ofCrAnListF, show φs1 ++ φ3 :: φ2 :: φ1 :: φs2 = φs1 ++ [φ3, φ2, φ1] ++ φs2
      by simp, crAnTimeOrderList, h1]
    simp only [decide_not,
      Bool.decide_and, ofCrAnListF_append, map_smul, map_mul, l1, l2, mul_assoc]
    congr 1
    have hp : List.Perm [φ3, φ2, φ1] [φ1, φ2, φ3] := (List.Perm.swap φ2 φ3 [φ1]).trans hp231
    rw [crAnTimeOrderSign, Wick.koszulSign_perm_eq _ _ φ1 _ _ _ _ _ hp, ← crAnTimeOrderSign]
    · simp
    · simp_all
  rw [h123, h132, h231, h321]
  trans crAnTimeOrderSign (φs1 ++ φ1 :: φ2 :: φ3 :: φs2) • (ι (ofCrAnListF l1) *
    ι [ofCrAnOpF φ1, [ofCrAnOpF φ2, ofCrAnOpF φ3]ₛF]ₛF *
    ι (ofCrAnListF l2)); swap
  · simp
  rw [mul_assoc, ← ofCrAnListF_singleton, ← ofCrAnListF_singleton, ← ofCrAnListF_singleton,
    superCommuteF_ofCrAnListF_ofCrAnListF]
  simp only [List.singleton_append, ofList_singleton, map_sub, map_smul]
  rw [superCommuteF_ofCrAnListF_ofCrAnListF, superCommuteF_ofCrAnListF_ofCrAnListF]
  simp [List.cons_append, List.nil_append, ofList_singleton, map_sub,
    map_smul, mul_sub, sub_mul, Semigroup.mul_assoc]
  module

lemma ι_timeOrderF_superCommuteF_superCommuteF_ofCrAnListF {φ1 φ2 φ3 : 𝓕.CrAnFieldOp}
    (φs1 φs2 : List 𝓕.CrAnFieldOp) :
    ι 𝓣ᶠ(ofCrAnListF φs1 * [ofCrAnOpF φ1, [ofCrAnOpF φ2, ofCrAnOpF φ3]ₛF]ₛF * ofCrAnListF φs2)
    = 0 := by
  by_cases h :
      crAnTimeOrderRel φ1 φ2 ∧ crAnTimeOrderRel φ1 φ3 ∧
      crAnTimeOrderRel φ2 φ1 ∧ crAnTimeOrderRel φ2 φ3 ∧
      crAnTimeOrderRel φ3 φ1 ∧ crAnTimeOrderRel φ3 φ2
  · exact ι_timeOrderF_superCommuteF_superCommuteF_eq_time_ofCrAnListF φs1 φs2 h
  · rw [timeOrderF_timeOrderF_mid]
    simp [timeOrderF_superCommuteF_ofCrAnOpF_superCommuteF_all_not_crAnTimeOrderRel _ _ _ h]

@[simp]
lemma ι_timeOrderF_superCommuteF_superCommuteF {φ1 φ2 φ3 : 𝓕.CrAnFieldOp}
    (a b : 𝓕.FieldOpFreeAlgebra) :
    ι 𝓣ᶠ(a * [ofCrAnOpF φ1, [ofCrAnOpF φ2, ofCrAnOpF φ3]ₛF]ₛF * b) = 0 := by
  let pb (b : 𝓕.FieldOpFreeAlgebra) (hc : b ∈ Submodule.span ℂ (Set.range ofCrAnListFBasis)) :
    Prop := ι 𝓣ᶠ(a * [ofCrAnOpF φ1, [ofCrAnOpF φ2, ofCrAnOpF φ3]ₛF]ₛF * b) = 0
  change pb b (Basis.mem_span _ b)
  apply Submodule.span_induction
  · rintro x ⟨φs, rfl⟩
    simp only [ofListBasis_eq_ofList, pb]
    let pa (a : 𝓕.FieldOpFreeAlgebra) (hc : a ∈ Submodule.span ℂ (Set.range ofCrAnListFBasis)) :
      Prop := ι 𝓣ᶠ(a * [ofCrAnOpF φ1, [ofCrAnOpF φ2, ofCrAnOpF φ3]ₛF]ₛF * ofCrAnListF φs) = 0
    change pa a (Basis.mem_span _ a)
    apply Submodule.span_induction
    · rintro x ⟨φs', rfl⟩
      simpa only [ofListBasis_eq_ofList, pa] using
        ι_timeOrderF_superCommuteF_superCommuteF_ofCrAnListF φs' φs
    · simp [pa]
    · intro x y hx hy hpx hpy
      simp_all [pa, add_mul]
    · intro x hx hpx
      simp_all [pa]
  · simp [pb]
  · intro x y hx hy hpx hpy
    simp_all [pb,mul_add]
  · intro x hx hpx
    simp_all [pb]

example (c1 c2 : ℂ) (a : 𝓕.WickAlgebra) : c1 • c2 • a =
  c2 • c1 • a := smul_comm c1 c2 a

lemma ι_timeOrderF_superCommuteF_eq_time {φ ψ : 𝓕.CrAnFieldOp}
    (hφψ : crAnTimeOrderRel φ ψ) (hψφ : crAnTimeOrderRel ψ φ) (a b : 𝓕.FieldOpFreeAlgebra) :
    ι 𝓣ᶠ(a * [ofCrAnOpF φ, ofCrAnOpF ψ]ₛF * b) =
    ι ([ofCrAnOpF φ, ofCrAnOpF ψ]ₛF * 𝓣ᶠ(a * b)) := by
  let C := superCommuteF (ofCrAnOpF φ) (ofCrAnOpF ψ)
  change (ι.toLinearMap ∘ₗ timeOrderF ∘ₗ mulLinearMap (a * C)) b =
    (ι.toLinearMap ∘ₗ mulLinearMap C ∘ₗ timeOrderF ∘ₗ mulLinearMap a) b
  refine LinearMap.congr_fun (ofCrAnListFBasis.ext fun φs ↦ ?_) b
  simp only [ofListBasis_eq_ofList, LinearMap.coe_comp, Function.comp_apply, mulLinearMap_apply,
    AlgHom.toLinearMap_apply]
  rw [mul_assoc]
  change (ι.toLinearMap ∘ₗ timeOrderF ∘ₗ mulLinearMap.flip (C * ofCrAnListF φs)) a =
    (ι.toLinearMap ∘ₗ mulLinearMap C ∘ₗ timeOrderF ∘ₗ
      mulLinearMap.flip (ofCrAnListF φs)) a
  refine LinearMap.congr_fun (ofCrAnListFBasis.ext fun φs' ↦ ?_) a
  simp only [ofListBasis_eq_ofList, LinearMap.coe_comp, Function.comp_apply, mulLinearMap_apply,
    LinearMap.flip_apply, AlgHom.toLinearMap_apply, C]
  rw [← mul_assoc]
  let l := List.insertionSort crAnTimeOrderRel (φs' ++ φs)
  let p := List.takeWhile (fun c => ¬ crAnTimeOrderRel φ c) l
  let q := List.filter (fun c => crAnTimeOrderRel φ c ∧ crAnTimeOrderRel c φ) φs'
  let r := List.filter (fun c => crAnTimeOrderRel φ c ∧ crAnTimeOrderRel c φ) φs
  let s := List.filter (fun c => crAnTimeOrderRel φ c ∧ ¬ crAnTimeOrderRel c φ) l
  let u := φs' ++ φ :: ψ :: φs
  let v := φs' ++ ψ :: φ :: φs
  let w := φs' ++ [φ, ψ] ++ φs
  let x := ι (ofCrAnListF p)
  let y := ι (ofCrAnListF q)
  let z := ι (ofCrAnListF r)
  let t := ι (ofCrAnListF s)
  let d := 𝓢(𝓕.crAnStatistics φ, 𝓕.crAnStatistics ψ)
  calc ι
        /- Split the commutator. -/
        _ = crAnTimeOrderSign u • ι (ofCrAnListF (crAnTimeOrderList u)) -
            crAnTimeOrderSign v •
          d •
            ι (ofCrAnListF (crAnTimeOrderList v)) := by
          conv_lhs =>
            rw [← ofCrAnListF_singleton, ← ofCrAnListF_singleton,
              superCommuteF_ofCrAnListF_ofCrAnListF]
            simp [mul_sub, sub_mul, ← ofCrAnListF_append]
            rw [timeOrderF_ofCrAnListF, timeOrderF_ofCrAnListF]
          simp only [map_smul]
          simp [u, v, d, smul_smul, mul_comm]
        /- Simplify the signs. -/
        _ = crAnTimeOrderSign u •
          (ι (ofCrAnListF (crAnTimeOrderList u)) -
          d •
            ι (ofCrAnListF (crAnTimeOrderList v))) := by
          dsimp only [u, v]
          rw [crAnTimeOrderSign_swap_eq_time hφψ hψφ]
          rw [smul_sub]
        /- Splitting the time-ordered lists. -/
        _ = crAnTimeOrderSign w •
          (x * y *
              ι (ofCrAnListF [φ, ψ]) *
              z * t -
          d •
          x * y *
              ι (ofCrAnListF [ψ, φ]) *
              z * t) := by
          have h1 := insertionSort_of_eq_list 𝓕.crAnTimeOrderRel φ φs' [φ, ψ] φs
            (by simp [hφψ, hψφ])
          rw [crAnTimeOrderList, show u = w by simp [u, w], h1]
          have h2 := insertionSort_of_eq_list 𝓕.crAnTimeOrderRel φ φs' [ψ, φ] φs
            (by simp [hφψ, hψφ])
          rw [crAnTimeOrderList, show v = φs' ++ [ψ, φ] ++ φs by simp [v], h2]
          repeat rw [ofCrAnListF_append]
          simp only [l, p, q, r, s, x, y, z, t, decide_not, Bool.decide_and, map_mul,
            Algebra.smul_mul_assoc]
        _ = crAnTimeOrderSign w •
            (x * y *
              (ι (ofCrAnListF [φ, ψ]) - d •
                ι (ofCrAnListF [ψ, φ])) *
              z * t) := by
            simp only [mul_sub, sub_mul, Algebra.mul_smul_comm, Algebra.smul_mul_assoc]
        _ = crAnTimeOrderSign w •
            (x * y *
              ι [ofCrAnOpF φ, ofCrAnOpF ψ]ₛF *
              z * t) := by
            congr
            rw [superCommuteF_ofCrAnOpF_ofCrAnOpF, ← ofCrAnListF_singleton,
              ← ofCrAnListF_singleton]
            simp [d, ← ofCrAnListF_append]
  rw [Subalgebra.mem_center_iff.mp (ι_superCommuteF_ofCrAnOpF_ofCrAnOpF_mem_center φ ψ)]
  repeat rw [mul_assoc]
  rw [← map_mul, ← map_mul, ← map_mul, ← ofCrAnListF_append, ← ofCrAnListF_append,
    ← ofCrAnListF_append]
  have h1 := insertionSort_of_takeWhile_filter 𝓕.crAnTimeOrderRel φ φs' φs
  dsimp only [l, p, q, r, s, w, x, y, z, t] at h1 ⊢
  simp only [decide_not, Bool.decide_and, List.append_assoc, List.cons_append,
    List.nil_append, map_mul] at h1 ⊢
  rw [← h1, ← crAnTimeOrderList]
  by_cases hq : (𝓕 |>ₛ φ) ≠ (𝓕 |>ₛ ψ)
  · simp [ι_superCommuteF_of_diff_statistic hq]
  · rw [crAnTimeOrderSign, Wick.koszulSign_eq_rel_eq_stat _ _ hφψ hψφ
      (not_ne_iff.mp hq).symm,
      ← crAnTimeOrderSign, ← ofCrAnListF_append, timeOrderF_ofCrAnListF]
    simp only [map_smul, Algebra.mul_smul_comm]
