import Mathlib
import Aesop

set_option maxHeartbeats 0

open Set Function



theorem putnam_1964_a4
(u : ℕ → ℤ)
(boundedu : ∃ B T : ℤ, ∀ n : ℕ, B ≤ u n ∧ u n ≤ T)
(hu : ∀ n ≥ 4, u n = ((u (n - 1) + u (n - 2) + u (n - 3) * u (n - 4)) : ℝ) / (u (n - 1) * u (n - 2) + u (n - 3) + u (n - 4)) ∧ (u (n - 1) * u (n - 2) + u (n - 3) + u (n - 4)) ≠ 0)
: (∃ N c : ℕ, c > 0 ∧ ∀ n ≥ N, u (n + c) = u n) := by
  obtain ⟨B, T, hB⟩ := boundedu
  let f : ℕ → ℤ × ℤ × ℤ × ℤ := fun n ↦ (u n, u (n + 1), u (n + 2), u (n + 3))
  let S : Set (ℤ × ℤ × ℤ × ℤ) :=
    Set.Icc B T ×ˢ (Set.Icc B T ×ˢ (Set.Icc B T ×ˢ Set.Icc B T))
  have hfin : S.Finite := (Set.finite_Icc B T).prod ((Set.finite_Icc B T).prod
    ((Set.finite_Icc B T).prod (Set.finite_Icc B T)))
  obtain ⟨i, j, hij, hf⟩ := hfin.exists_lt_map_eq_of_forall_mem (f := f) (fun n ↦ by
    exact ⟨hB n, hB (n + 1), hB (n + 2), hB (n + 3)⟩)
  have hf' : u i = u j ∧ u (i + 1) = u (j + 1) ∧ u (i + 2) = u (j + 2) ∧
      u (i + 3) = u (j + 3) := by
    simpa only [f, Prod.mk.injEq] using hf
  have huv : ∀ m, u (i + m) = u (j + m) := by
    intro m
    induction m using Nat.strong_induction_on with
    | h m ih =>
      match m with
      | 0 => simpa using hf'.1
      | 1 => simpa using hf'.2.1
      | 2 => simpa using hf'.2.2.1
      | 3 => simpa using hf'.2.2.2
      | m + 4 =>
        have hi := (hu (i + (m + 4)) (by omega)).1
        have hj := (hu (j + (m + 4)) (by omega)).1
        have h0 := ih m (by omega)
        have h1 := ih (m + 1) (by omega)
        have h2 := ih (m + 2) (by omega)
        have h3 := ih (m + 3) (by omega)
        simp only [show i + (m + 4) - 1 = i + (m + 3) by omega,
          show i + (m + 4) - 2 = i + (m + 2) by omega,
          show i + (m + 4) - 3 = i + (m + 1) by omega,
          show i + (m + 4) - 4 = i + m by omega] at hi
        simp only [show j + (m + 4) - 1 = j + (m + 3) by omega,
          show j + (m + 4) - 2 = j + (m + 2) by omega,
          show j + (m + 4) - 3 = j + (m + 1) by omega,
          show j + (m + 4) - 4 = j + m by omega] at hj
        have hr : (u (i + (m + 4)) : ℝ) = u (j + (m + 4)) := by
          rw [hi, hj, h0, h1, h2, h3]
        exact Int.cast_injective hr
  refine ⟨i, j - i, by omega, ?_⟩
  intro n hn
  have hni : i + (n - i) = n := by omega
  have hnj : j + (n - i) = n + (j - i) := by omega
  simpa only [hni, hnj] using (huv (n - i)).symm
