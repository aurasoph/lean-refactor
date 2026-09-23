import Mathlib
import Aesop

set_option maxHeartbeats 0

open Set Function



theorem putnam_1964_a4
(u : ℕ → ℤ)
(boundedu : ∃ B T : ℤ, ∀ n : ℕ, B ≤ u n ∧ u n ≤ T)
(hu : ∀ n ≥ 4, u n = ((u (n - 1) + u (n - 2) + u (n - 3) * u (n - 4)) : ℝ) / (u (n - 1) * u (n - 2) + u (n - 3) + u (n - 4)) ∧ (u (n - 1) * u (n - 2) + u (n - 3) + u (n - 4)) ≠ 0)
: (∃ N c : ℕ, c > 0 ∧ ∀ n ≥ N, u (n + c) = u n) := by
  let f := fun n => (u n, u (n + 1), u (n + 2), u (n + 3))
  obtain ⟨B, T, hB⟩ := boundedu
  obtain ⟨i, j, hij, he⟩ :=
    (Set.finite_Icc (B, B, B, B) (T, T, T, T)).exists_lt_map_eq_of_forall_mem
      (f := f) (fun n => show f n ∈ Set.Icc (B, B, B, B) (T, T, T, T) from
        ⟨⟨(hB n).1, (hB (n+1)).1, (hB (n+2)).1, (hB (n+3)).1⟩,
         ⟨(hB n).2, (hB (n+1)).2, (hB (n+2)).2, (hB (n+3)).2⟩⟩)
  have hrec := fun a : ℕ => (hu (a + 4) (by omega)).1
  simp only [show ∀ a : ℕ, a + 4 - 1 = a + 3 from fun a => by omega,
    show ∀ a : ℕ, a + 4 - 2 = a + 2 from fun a => by omega,
    show ∀ a : ℕ, a + 4 - 3 = a + 1 from fun a => by omega,
    Nat.add_sub_cancel] at hrec
  have step (a b : ℕ) (h : f a = f b) : f (a + 1) = f (b + 1) := by
    simp only [f, Prod.mk.injEq] at h
    have hn : u (a + 4) = u (b + 4) := by
      apply Int.cast_injective (α := ℝ)
      rw [hrec a, hrec b, h.1, h.2.1, h.2.2.1, h.2.2.2]
    simpa only [f, Nat.add_assoc, Nat.reduceAdd, Prod.mk.injEq] using
      And.intro h.2.1 (And.intro h.2.2.1 (And.intro h.2.2.2 hn))
  have hall (k : ℕ) : f (i + k) = f (j + k) := by
    induction k with
    | zero => exact he
    | succ k ih => exact step (i+k) (j+k) ih
  refine ⟨i, j - i, Nat.sub_pos_of_lt hij, ?_⟩
  intro n hn
  have h := congrArg Prod.fst (hall (n-i))
  change u (i + (n-i)) = u (j + (n-i)) at h
  convert h.symm using 1 <;> congr 1 <;> omega
