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
  have hI : (P : Set (Set S)).Intersecting := by
    intro A hA B hB h
    exact hPP A hA B hB (Set.disjoint_iff_inter_eq_empty.mp h)
  have hm : ∀ Q : Finset (Set S), (Q : Set (Set S)).Intersecting → P ⊆ Q → P = Q := by
    intro Q hQ hPQ
    apply Finset.Subset.antisymm hPQ
    intro T hT
    by_contra hTP
    apply hPS
    refine ⟨T, hTP, fun U hU hTU => ?_⟩
    exact hQ hT (hPQ hU) (Set.disjoint_iff_inter_eq_empty.mpr hTU)
  have hc := hI.is_max_iff_card_eq.mp hm
  obtain ⟨n, hn⟩ := Nat.exists_eq_succ_of_ne_zero Fintype.card_ne_zero
  rw [hn] at hc ⊢
  simpa [Fintype.card_set, pow_succ] using hc
