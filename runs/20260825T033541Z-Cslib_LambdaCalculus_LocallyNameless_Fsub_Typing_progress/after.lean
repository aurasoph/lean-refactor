/-
Copyright (c) 2025 Chris Henson. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Chris Henson
-/

module

public import Cslib.Languages.LambdaCalculus.LocallyNameless.Fsub.Typing

/-! # λ-calculus

The λ-calculus with polymorphism and subtyping, with a locally nameless representation of syntax.
This file proves type safety.

## References

* [A. Chargueraud, *The Locally Nameless Representation*][Chargueraud2012]
* See also <https://www.cis.upenn.edu/~plclub/popl08-tutorial/code/>, from which
  this is adapted

-/

public section

namespace Cslib

variable {Var : Type*} [HasFresh Var] [DecidableEq Var]

namespace LambdaCalculus.LocallyNameless.Fsub

open Context List Env.Wf Term Ty

variable {t : Term Var}

/-- Any reduction step preserves typing. -/
lemma Typing.preservation (der : Typing Γ t τ) (step : t ⭢βᵛ t') : Typing Γ t' τ := by
  induction der generalizing t'
  case app Γ _ σ τ _ _ _ _ _ =>
    cases step
    case appₗ | appᵣ => grind
    case abs der _ _ =>
      have sub : Sub Γ (σ.arrow τ) (σ.arrow τ) := by grind [Sub.refl]
      have ⟨_, _, ⟨_, _⟩⟩ := der.abs_inv sub
      grind [fresh_exists <| free_union [fvTm] Var, openTm_substTm_intro, subst_tm, Sub.weaken]
  case tapp Γ _ σ τ σ' _ _ _ =>
    cases step
    case tabs der _ _ =>
      have sub : Sub Γ (σ.all τ) (σ.all τ) := by grind [Sub.refl]
      have ⟨_, _, ⟨_, _⟩⟩ := der.tabs_inv sub
      have ⟨X, mem⟩ := fresh_exists <| free_union [Ty.fv, fvTy] Var
      simp at mem
      have : Γ = (Context.mapVal (·[X := σ']) []) ++ Γ := by grind
      rw [openTy_substTy_intro (X := X), open_subst_intro (X := X)] <;> grind [subst_ty]
    case tapp => grind
  case let' Γ _ _ _ _ L der _ ih₁ _ =>
    cases step
    case let_bind red₁ _ => apply Typing.let' L (ih₁ red₁); grind
    case let_body =>
      grind [fresh_exists <| free_union [fvTm] Var, openTm_substTm_intro, subst_tm]
  case case Γ _ σ τ _ _ _ L _ _ _ ih₁ _ _ =>
    have sub : Sub Γ (σ.sum τ) (σ.sum τ) := by grind [Sub.refl]
    have : Γ = [] ++ Γ := by rfl
    cases step
    case «case» red₁ _ _ => apply Typing.case L (ih₁ red₁) <;> grind
    case case_inl der _ _ =>
      have ⟨_, ⟨_, _⟩⟩ := der.inl_inv sub
      grind [fresh_exists <| free_union [fvTm] Var, openTm_substTm_intro, subst_tm]
    case case_inr der _ _ =>
      have ⟨_, ⟨_, _⟩⟩ := der.inr_inv sub
      grind [fresh_exists <| free_union [fvTm] Var, openTm_substTm_intro, subst_tm]
  all_goals grind [cases Red]


lemma Typing.progress (der : Typing [] t τ) : t.Value ∨ ∃ t', t ⭢βᵛ t' := by
  generalize eq : [] = Γ at der
  have der' : Typing Γ t τ := der
  induction der <;> subst eq
  case var mem => grind
  case app l r ih₁ ih₂ =>
    cases ih₁ rfl l with
    | inr h => exact .inr ⟨_, .appₗ r.wf.2.1 h.choose_spec⟩
    | inl v₁ =>
      cases ih₂ rfl r with
      | inr h => exact .inr ⟨_, .appᵣ v₁ h.choose_spec⟩
      | inl v₂ =>
        obtain ⟨_, b, rfl⟩ := l.canonical_form_abs v₁
        exact .inr ⟨_, .abs l.wf.2.1 v₂⟩
  case tapp der sub ih =>
    cases ih rfl der with
    | inr h => exact .inr ⟨_, .tapp sub.wf.2.1.lc h.choose_spec⟩
    | inl v =>
      obtain ⟨_, b, rfl⟩ := der.canonical_form_tabs v
      exact .inr ⟨_, .tabs der.wf.2.1 sub.wf.2.1.lc⟩
  case let' der _ ih _ =>
    have ⟨_, body⟩ := body_let.mp der'.wf.2.1
    cases ih rfl der with
    | inl v => exact .inr ⟨_, .let_body v body⟩
    | inr r => exact .inr ⟨_, .let_bind r.choose_spec body⟩
  case inl der _ ih => exact (ih rfl der).imp Value.inl fun ⟨u, r⟩ => ⟨_, .inl r⟩
  case inr der _ ih => exact (ih rfl der).imp Value.inr fun ⟨u, r⟩ => ⟨_, .inr r⟩
  case case der _ _ ih _ _ =>
    have ⟨_, b₂, b₃⟩ := body_case.mp der'.wf.2.1
    cases ih rfl der with
    | inr r => exact .inr ⟨_, .case r.choose_spec b₂ b₃⟩
    | inl v =>
      obtain ⟨u, rfl | rfl⟩ := der.canonical_form_sum v
      all_goals cases v <;> grind only [Red.case_inl, Red.case_inr]
  case sub => grind
  case abs L _ _ =>
    left
    constructor
    apply LC.abs L <;> grind only [→ wf, cases Term.LC]
  case tabs L _ _ =>
    left
    constructor
    apply LC.tabs L <;> grind only [→ wf, cases Term.LC]
