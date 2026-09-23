import Mathlib
import Aesop

set_option maxHeartbeats 0

open Filter Topology Real



theorem putnam_1995_a3
(relation : (Fin 9 → ℤ) → (Fin 9 → ℤ) → Prop)
(digits_to_num : (Fin 9 → ℤ) → ℤ)
(hdigits_to_num : digits_to_num = fun dig => ∑ i : Fin 9, (dig i) * 10^i.1)
(hrelation : ∀ d e : (Fin 9 → ℤ), relation d e ↔ (∀ i : Fin 9, d i < 10 ∧ d i ≥ 0 ∧ e i < 10 ∧ e i ≥ 0) ∧ (∀ i : Fin 9, 7 ∣ (digits_to_num (fun j : Fin 9 => if j = i then e j else d j))))
: ∀ d e f : (Fin 9 → ℤ), ((relation d e) ∧ (relation e f)) → (∀ i : Fin 9, 7 ∣ d i - f i) := by
  rintro d e f ⟨hde, hef⟩ i
  have hrep (a b : Fin 9 → ℤ) (h : relation a b) (j : Fin 9) :
      7 ∣ digits_to_num a + (b j - a j) * 10 ^ j.1 := by
    have hs : digits_to_num (fun k => if k = j then b k else a k) =
        digits_to_num a + (b j - a j) * 10 ^ j.1 := by
      rw [hdigits_to_num]
      calc
        ∑ k, (if k = j then b k else a k) * 10 ^ k.1 =
            ∑ k, (a k * 10 ^ k.1 + (if k = j then (b k - a k) * 10 ^ k.1 else 0)) := by
              apply Finset.sum_congr rfl
              intro k _
              split
              · subst k
                simp only [sub_mul]
                abel
              · simp only [add_zero]
        _ = ∑ k, a k * 10 ^ k.1 + (b j - a j) * 10 ^ j.1 := by
          rw [Finset.sum_add_distrib]
          simp only [Finset.sum_ite_eq', Finset.mem_univ, if_pos]
    rw [← hs]
    exact ((hrelation a b).mp h).2 j
  have hd := hrep d e hde
  have he := hrep e f hef
  have hs : 7 ∣ digits_to_num d + digits_to_num e := by
    have h := Finset.dvd_sum (s := Finset.univ) (fun j _ => hd j)
    have heq : ∑ j : Fin 9, (digits_to_num d + (e j - d j) * 10 ^ j.1) =
        digits_to_num d + digits_to_num e + 7 * digits_to_num d := by
      rw [hdigits_to_num, Finset.sum_add_distrib]
      simp only [Finset.sum_const, Finset.card_univ, Fintype.card_fin, nsmul_eq_mul]
      simp_rw [sub_mul]
      rw [Finset.sum_sub_distrib]
      ring
    rw [heq] at h
    simpa only [add_sub_cancel_right] using
      dvd_sub h (dvd_mul_right 7 (digits_to_num d))
  have hp : 7 ∣ (f i - d i) * 10 ^ i.1 := by
    convert dvd_sub (dvd_add (hd i) (he i)) hs using 1; ring
  rw [← neg_sub]
  exact dvd_neg.mpr <|
    (show IsCoprime (7 : ℤ) 10 by norm_num).pow_right.dvd_of_dvd_mul_right hp
