import Mathlib
import Aesop

set_option maxHeartbeats 0

open Set Function



theorem putnam_1964_a4
(u : ℕ → ℤ)
(boundedu : ∃ B T : ℤ, ∀ n : ℕ, B ≤ u n ∧ u n ≤ T)
(hu : ∀ n ≥ 4, u n = ((u (n - 1) + u (n - 2) + u (n - 3) * u (n - 4)) : ℝ) / (u (n - 1) * u (n - 2) + u (n - 3) + u (n - 4)) ∧ (u (n - 1) * u (n - 2) + u (n - 3) + u (n - 4)) ≠ 0)
: (∃ N c : ℕ, c > 0 ∧ ∀ n ≥ N, u (n + c) = u n) := by
  obtain ⟨B, T, h⟩ := boundedu
  let f : ℕ → Fin 4 → Set.Icc B T := fun n k => ⟨u (n + k), h _⟩
  obtain ⟨i, j, hlt, hf⟩ := Set.finite_univ.exists_lt_map_eq_of_forall_mem (f := f)
    fun _ => Set.mem_univ _
  have hshift (m) : u (i + m) = u (j + m) :=
    Nat.strong_induction_on m fun m ih => by
    by_cases hm : m < 4
    · exact congrArg Subtype.val (congrFun hf ⟨m, hm⟩)
    · apply Int.cast_injective (α := ℝ)
      rw [(hu (i + m) (by omega)).1, (hu (j + m) (by omega)).1]
      have hp (k) (hk : 0 < k ∧ k ≤ 4) :
          u (i + m - k) = u (j + m - k) := by
        have hkm := hk.2.trans (Nat.not_lt.mp hm)
        rw [Nat.add_sub_assoc hkm i, Nat.add_sub_assoc hkm j]
        exact ih (m - k) (Nat.sub_lt_of_pos_le hk.1 hkm)
      rw [hp 1 (by decide), hp 2 (by decide), hp 3 (by decide), hp 4 (by decide)]
  refine ⟨i, j - i, Nat.sub_pos_of_lt hlt, ?_⟩
  intro n hn
  simpa only [show n + (j - i) = j + (n - i) by omega,
    Nat.add_sub_of_le hn] using (hshift (n - i)).symm
