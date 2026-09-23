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
  have maximal (A : Set S) (h : ∀ U ∈ P, A ∩ U ≠ ∅) : A ∈ P := by
    by_contra hn
    exact hPS ⟨A, hn, h⟩
  have hc (A : Set S) : Aᶜ ∈ P ↔ A ∉ P := by
    constructor
    · intro hAc hA
      exact hPP A hA Aᶜ hAc (Set.inter_compl_self A)
    · intro hn
      apply maximal
      intro U hU hAU
      have hUA : U ⊆ A :=
        disjoint_compl_left_iff.mp (Set.disjoint_iff_inter_eq_empty.mpr hAU)
      apply hn
      apply maximal
      intro V hV hAV
      exact hPP U hU V hV
        ((Set.disjoint_iff_inter_eq_empty.mpr hAV).mono_left hUA).eq_bot
  have hcard : P.card = Pᶜ.card := by
    apply Finset.card_bij' (fun A _ => Aᶜ) (fun A _ => Aᶜ)
    · intros
      exact compl_compl _
    · intros
      exact compl_compl _
    · intro A hA
      exact Finset.mem_compl.mpr (fun h => (hc A).mp h hA)
    · intro A hA
      exact (hc A).2 (Finset.mem_compl.mp hA)
  have hsum := Finset.card_add_card_compl P
  rw [← hcard, Fintype.card_set] at hsum
  have hn : Fintype.card S - 1 + 1 = Fintype.card S :=
    Nat.sub_add_cancel (Fintype.card_pos_iff.mpr inferInstance)
  have hp : 2 ^ (Fintype.card S - 1) * 2 = 2 ^ Fintype.card S := by
    rw [← pow_succ, hn]
  omega
