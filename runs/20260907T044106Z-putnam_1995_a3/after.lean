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
  have step (d e : Fin 9 → ℤ) (h : relation d e) (i : Fin 9) :
      7 ∣ (e i - d i) * 10 ^ i.1 + digits_to_num d := by
    have hi := ((hrelation d e).mp h).2 i
    rw [hdigits_to_num] at hi ⊢
    convert hi using 1
    symm
    calc
      _ = ∑ j : Fin 9, ((if j = i then (e j - d j) * 10 ^ j.1 else 0) +
          d j * 10 ^ j.1) := by
        apply Finset.sum_congr rfl
        intro j _
        dsimp only
        split_ifs <;> ring
      _ = _ := by rw [Finset.sum_add_distrib]; simp
  intro d e f h i
  have hd := step d e h.1
  have he := step e f h.2
  have hs : 7 ∣ digits_to_num e - digits_to_num d + 9 * digits_to_num d := by
    simpa [sub_mul, Finset.sum_add_distrib, Finset.sum_sub_distrib, hdigits_to_num]
      using Finset.dvd_sum (fun j (_ : j ∈ (Finset.univ : Finset (Fin 9))) => hd j)
  have hp : 7 ∣ (d i - f i) * 10 ^ i.1 := by
    convert dvd_sub (dvd_sub hs (dvd_mul_right 7 (digits_to_num d)))
      (dvd_add (hd i) (he i)) using 1 <;> ring
  have prime : Prime (7 : ℤ) := Int.prime_iff_natAbs_prime.mpr (by decide)
  exact (prime.dvd_mul.mp hp).resolve_right
    (fun hp => (by norm_num : ¬ (7 : ℤ) ∣ 10) (prime.dvd_of_dvd_pow hp))
