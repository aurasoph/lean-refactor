import Mathlib
import Aesop

set_option maxHeartbeats 0

open Set Function Filter Topology



theorem putnam_1964_b2
(S : Type*) [Fintype S] [Nonempty S]
(P : Finset (Set S))
(hPP : ∀ T ∈ P, ∀ U ∈ P, T ∩ U ≠ ∅)
(hPS : ¬∃ T : Set S, T ∉ P ∧ (∀ U ∈ P, T ∩ U ≠ ∅))
: (P.card = 2 ^ (Fintype.card S - 1)) := by
  classical
  push_neg at hPS
  have hc A : A ∈ P ↔ Aᶜ ∉ P := by
    constructor
    · intro hA hAc
      simpa using hPP A hA Aᶜ hAc
    · intro hA
      by_contra hAc
      obtain ⟨U, hU, hAU⟩ := hPS A hAc
      obtain ⟨V, hV, hAV⟩ := hPS Aᶜ hA
      apply hPP U hU V hV
      rw [← disjoint_iff_inter_eq_empty] at hAU hAV ⊢
      exact disjoint_compl_right.mono hAU.subset_compl_left hAV.subset_compl_left
  have hcard : P.card = Pᶜ.card :=
    Finset.card_bijective compl compl_bijective
      (by simpa using hc)
  have htwice := Finset.card_compl_add_card P
  rw [← hcard, Fintype.card_set, ← Nat.sub_add_cancel Fintype.card_pos, pow_succ,
    Nat.succ_eq_add_one,
    Nat.zero_add] at htwice
  omega
