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
  intro d e f h
  have repl (x y : Fin 9 → ℤ) (i : Fin 9) :
      digits_to_num (fun j => if j = i then y j else x j) =
        digits_to_num x + (y i - x i) * 10 ^ i.1 := by
    classical
    rw [hdigits_to_num]
    calc
      _ = ∑ j, (x j * 10 ^ j.1 +
          if j = i then (y j - x j) * 10 ^ j.1 else 0) := by
        apply Finset.sum_congr rfl
        intro j _
        split_ifs with hj <;> simp [hj, sub_mul]
      _ = _ := by rw [Finset.sum_add_distrib]; simp
  have total (x y : Fin 9 → ℤ) (hr : relation x y) :
      7 ∣ digits_to_num x + digits_to_num y := by
    have hs : 7 ∣ ∑ i,
        (digits_to_num x + (y i - x i) * 10 ^ i.1) := by
      apply Finset.dvd_sum
      intro i _
      rw [← repl]
      exact ((hrelation x y).mp hr).2 i
    have hid : (∑ i,
        (digits_to_num x + (y i - x i) * 10 ^ i.1)) =
        8 * digits_to_num x + digits_to_num y := by
      rw [hdigits_to_num]
      simp only [sub_mul, Finset.sum_add_distrib, Finset.sum_sub_distrib]
      simp
      ring
    rw [hid] at hs
    convert dvd_sub hs (dvd_mul_right 7 (digits_to_num x)) using 1 <;> ring
  intro i
  have ha : 7 ∣ digits_to_num d + (e i - d i) * 10 ^ i.1 := by
    rw [← repl]
    exact ((hrelation d e).mp h.1).2 i
  have hb : 7 ∣ digits_to_num e + (f i - e i) * 10 ^ i.1 := by
    rw [← repl]
    exact ((hrelation e f).mp h.2).2 i
  have hp : 7 ∣ (d i - f i) * 10 ^ i.1 := by
    convert dvd_sub (total d e h.1) (dvd_add ha hb) using 1 <;> ring
  have hprime : Prime (7 : ℤ) := by norm_num
  obtain hi | hi := hprime.dvd_mul.mp hp
  · exact hi
  · have := hprime.dvd_of_dvd_pow hi
    norm_num at this
