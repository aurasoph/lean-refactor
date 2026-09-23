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
  let s : Set ℤ := Icc B T
  have hs : s.Finite := finite_Icc B T
  obtain ⟨i, j, hij, heq⟩ :=
    (hs.prod (hs.prod (hs.prod hs))).exists_lt_map_eq_of_forall_mem
      (f := fun n : ℕ => (u n, u (n + 1), u (n + 2), u (n + 3))) (by
        intro n
        simp only [mem_prod, s, mem_Icc]
        exact ⟨hB n, hB (n + 1), hB (n + 2), hB (n + 3)⟩)
  have hrec (a k : ℕ) :
      (u (a + (k + 4)) : ℝ) =
        (u (a + (k + 3)) + u (a + (k + 2)) + u (a + (k + 1)) * u (a + k)) /
          (u (a + (k + 3)) * u (a + (k + 2)) + u (a + (k + 1)) + u (a + k)) := by
    convert (hu (a + (k + 4)) (by omega)).1 using 1 <;> omega
  simp only [Prod.ext_iff] at heq
  have hall : ∀ m, u (i + m) = u (j + m) := by
    intro m
    induction m using Nat.strong_induction_on with
    | h m ih =>
      match m with
      | 0 => exact heq.1
      | 1 => exact heq.2.1
      | 2 => exact heq.2.2.1
      | 3 => exact heq.2.2.2
      | k + 4 =>
        have h : (u (i + (k + 4)) : ℝ) = u (j + (k + 4)) := by
          rw [hrec i k, hrec j k, ih k (by omega), ih (k + 1) (by omega),
            ih (k + 2) (by omega), ih (k + 3) (by omega)]
        exact_mod_cast h
  refine ⟨i, j - i, by omega, ?_⟩
  intro n hn
  convert (hall (n - i)).symm using 2 <;> omega
