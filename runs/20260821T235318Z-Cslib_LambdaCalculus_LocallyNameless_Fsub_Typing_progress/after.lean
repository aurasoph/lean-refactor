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
  induction der <;> subst eq
  case abs L h _ => exact .inl (.abs (Typing.abs L h).wf.2.1)
  case tabs L h _ => exact .inl (.tabs (Typing.tabs L h).wf.2.1)
  case app t₁ _ _ t₂ l r il ir =>
    right
    rcases il rfl with vl | ⟨_, hl⟩
    · rcases ir rfl with vr | ⟨_, hr⟩
      · obtain ⟨_, b, rfl⟩ := l.canonical_form_abs vl
        exact ⟨_, .abs l.wf.2.1 vr⟩
      · exact ⟨_, .appᵣ vl hr⟩
    · exact ⟨_, .appₗ r.wf.2.1 hl⟩
  case tapp σ' der sub ih =>
    right
    rcases ih rfl with v | ⟨_, h⟩
    · obtain ⟨_, b, rfl⟩ := der.canonical_form_tabs v
      exact ⟨_, .tabs der.wf.2.1 sub.wf.2.1.lc⟩
    · exact ⟨_, .tapp sub.wf.2.1.lc h⟩
  case let' t₁ σ t₂ τ L der h ih _ =>
    have ⟨_, body⟩ := Term.body_let.mp (Typing.let' L der h).wf.2.1
    right
    rcases ih rfl with v | ⟨_, r⟩
    · exact ⟨_, .let_body v body⟩
    · exact ⟨_, .let_bind r body⟩
  case case t₁ σ τ t₂ δ t₃ L der h₂ h₃ ih _ _ =>
    have ⟨_, body₂, body₃⟩ := Term.body_case.mp (Typing.case L der h₂ h₃).wf.2.1
    right
    rcases ih rfl with v | ⟨_, r⟩
    · obtain ⟨u, rfl | rfl⟩ := der.canonical_form_sum v
      · cases v with | inl v => exact ⟨_, .case_inl v body₂ body₃⟩
      · cases v with | inr v => exact ⟨_, .case_inr v body₂ body₃⟩
    · exact ⟨_, .case r body₂ body₃⟩
  all_goals
    aesop (add safe [Term.Value.inl, Term.Value.inr, Term.Red.inl, Term.Red.inr])
