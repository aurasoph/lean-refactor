/-
  Copyright Strata Contributors

  SPDX-License-Identifier: Apache-2.0 OR MIT
-/

import Init.Data.List.Basic
import Init.Data.List.Lemmas
import Strata.Languages.Core.Env
import Strata.Languages.Core.Identifiers
import Strata.Languages.Core.Program
import Strata.Languages.Core.ProgramType
import Strata.Languages.Core.WF
import Strata.DL.Lambda.Lambda
import Strata.Transform.CoreTransform
import Strata.Transform.CallElim
import Strata.DL.Imperative.CmdSemantics
import Strata.Languages.Core.StatementSemantics
import Strata.Languages.Core.StatementSemanticsProps
import Strata.DL.Util.ListUtils

/-! # Call Elimination Correctness Proof (DEPRECATED)

  We are deprecating this proof because it relies on the old big-step semantics for
  `Stmt`. This proof will be re-done with a new small-step semantics in the near
  future.

  This file contains the main proof that the call elimination transformation is
  semantics preserving (see `callElimStatementCorrect`).
  Additionally, `callElimBlockNoExcept` shows that the call elimination
  transformation always succeeds on well-formed statements.
-/

namespace CallElimCorrect
open Core Core.Transform CallElim

theorem CoreIdent.isGlob_isGlobOrLocl :
  PredImplies (CoreIdent.isGlob ·) (CoreIdent.isGlobOrLocl ·) := by
  intros x H
  simp [CoreIdent.isGlobOrLocl]
  exact Or.symm (Or.inr H)

theorem CoreIdent.isLocl_isGlobOrLocl :
  PredImplies (CoreIdent.isLocl ·) (CoreIdent.isGlobOrLocl ·) := by
  intros x H
  simp [CoreIdent.isGlobOrLocl]
  exact Or.symm (Or.inl H)

theorem CoreIdent.Disjoint_isTemp_isGlobOrLocl :
  PredDisjoint (CoreIdent.isTemp ·) (CoreIdent.isGlobOrLocl ·) := by
  intros x H1 H2
  simp [CoreIdent.isTemp] at H1
  simp [CoreIdent.isGlobOrLocl] at H2
  split at H1 <;> simp_all
  cases H2 <;> simp [CoreIdent.isGlob, CoreIdent.isLocl] at *

theorem CoreIdent.Disjoint_isLocl_isGlob :
  PredDisjoint (CoreIdent.isLocl ·) (CoreIdent.isGlob ·) := by
  intros x H1 H2
  simp [CoreIdent.isLocl] at H1
  simp [CoreIdent.isGlob] at H2
  split at H1 <;> simp_all

-- inidividual lemmas

theorem createHavocsApp :
createHavocs (a ++ b) = createHavocs a ++ createHavocs b := by
simp [createHavocs]

theorem createFvarsApp :
createFvars (a ++ b) = createFvars a ++ createFvars b := by
simp [createFvars]

theorem createFvarsLength :
(createFvars ls).length = ls.length := by
induction ls <;> simp [createFvars]

theorem filterIsGlobal_isSome :
  ident ∈ List.filter (isGlobalVar p) l →
  (p.find? DeclKind.var ident).isSome = true := by
  intros Hin
  simp [isGlobalVar] at Hin
  exact Hin.2

theorem getOldExprIdentTy_some : ∀ {p : Program} {id : Expression.Ident},
  (p.find? .var id).isSome = (getIdentTy? p id).isSome := by
  intros p id
  simp [Program.find?, getIdentTy?, Program.getVarTy?]
  split <;> simp_all

theorem getIdentTy!_store_same :
  getIdentTy! p x s = (Except.ok a', s') →
  s = s' := by
  intros H
  simp [getIdentTy!] at H
  generalize Hgt: (getIdentTy? p x) = gt at H
  split at H
  . cases H
  . simp [pure] at H
    cases H
    rfl

theorem getIdentTys!_store_same :
  getIdentTys! p xs s = (Except.ok a', s') →
  s = s' := by
  intros H
  induction xs generalizing s a' s' <;> simp [getIdentTys!, pure, ExceptT.pure, ExceptT.mk, StateT.pure] at H
  case nil =>
    cases H
    rfl
  case cons h t ih =>
    simp [bind, ExceptT.bind, ExceptT.mk, StateT.bind, ExceptT.bindCont] at H
    split at H
    next heq =>
    split at H
    . simp [StateT.bind, bind] at H
      split at H
      next heq' =>
      simp [ExceptT.bindCont] at H
      split at H
      . have H1 := getIdentTy!_store_same heq
        have H2 := ih heq'
        simp [StateT.pure, pure] at H
        cases H
        simp_all
      . cases H
    . cases H

theorem getIdentTy!_no_throw :
  (p.find? .var ident).isSome = true →
  ∃ r, (runWith ident (getIdentTy! p) cs).fst = (Except.ok r) := by
  intros H
  simp [runWith, StateT.run, getIdentTy!]
  have Hsome := @getOldExprIdentTy_some p ident
  simp [H] at Hsome
  simp [Option
... [truncated 85040 chars] ...
dExprIdent_len'] <;> simp_all
      . simp [genOldExprIdents]
        rw [← getIdentTys!_len heq']
        rw [genOldExprIdent_len'] <;> simp_all
    . cases Hgen
  . cases Hgen

theorem genOldExprIdentWFMono :
  CoreGenState.WF s →
  genOldExprIdent e s = (l, s') →
  CoreGenState.WF s' :=
  fun Hgen => CoreGenState.WFMono' Hgen

theorem genOldExprIdentsWFMono :
  CoreGenState.WF s →
  genOldExprIdents es s = (ls, s') →
  CoreGenState.WF s' := by
  intros Hwf Hgen
  simp [genOldExprIdents] at Hgen
  induction es generalizing s ls s' <;> simp at Hgen
  case nil =>
    simp [StateT.pure, pure] at Hgen
    cases Hgen <;> simp_all
  case cons h t ih =>
    simp [bind, StateT.bind, Functor.map, StateT.map, pure] at Hgen
    split at Hgen
    next a s₁ heq =>
    split at Hgen
    next a' s₂ heq' =>
    cases Hgen
    have HH := genOldExprIdentWFMono Hwf heq
    exact ih HH heq'

theorem genOldExprIdentsTripWFMono :
  CoreGenState.WF s →
  genOldExprIdentsTrip outs xs s = (Except.ok trips, s') →
  CoreGenState.WF s' := by
  intros Hwf Hgen
  simp [genOldExprIdentsTrip, bind, liftM,] at *
  simp [Functor.map, ExceptT.bind, ExceptT.bindCont, bind,
        monadLift, MonadLift.monadLift, ExceptT.lift,
        ExceptT.mk, StateT.bind] at Hgen
  split at Hgen
  split at Hgen
  . next heq =>
    simp [bind, StateT.bind] at Hgen
    split at Hgen
    next heq' =>
    simp [ExceptT.bindCont] at Hgen
    split at Hgen
    . cases Hgen
      simp [StateT.map, Functor.map] at heq
      cases heq
      generalize Hgen' : (genOldExprIdents xs s) = gen at heq'
      cases gen with
      | mk fst snd =>
      rw [← getIdentTys!_store_same heq']
      exact genOldExprIdentsWFMono Hwf Hgen'
    . cases Hgen
  . cases Hgen

theorem List.Subset.trans :
  List.Subset a b → b.Subset c → a.Subset c := fun H1 H2 _ Hin => H2 (H1 Hin)

theorem List.Subset.app :
  List.Subset a c → b.Subset c → (a ++ b).Subset c := by
  intros H1 H2
  intros x Hin
  simp at Hin
  cases Hin with
  | inl Hin =>
    exact H1 Hin
  | inr Hin =>
    exact H2 Hin


open OldExpressions in
theorem extractedOldExprInVars :
  NormalizedOldExpr post →
  (extractOldExprVars post).Subset
  (Imperative.HasVarsPure.getVars post) := by
  intros Hnorm
  induction post with
  | const m c => intros _ hin; simp [Imperative.HasVarsPure.getVars, extractOldExprVars, Lambda.LExpr.LExpr.getVars] at hin
  | op m o ty => intros _ hin; simp [Imperative.HasVarsPure.getVars, extractOldExprVars, Lambda.LExpr.LExpr.getVars] at hin
  | bvar m i => intros _ hin; simp [Imperative.HasVarsPure.getVars, extractOldExprVars, Lambda.LExpr.LExpr.getVars] at hin
  | fvar m n t => intros _ hin; simp [Imperative.HasVarsPure.getVars, extractOldExprVars, Lambda.LExpr.LExpr.getVars] at hin
  | app m fn e fn_ih e_ih =>
    intros Hnorm
    unfold extractOldExprVars at *
    split at Hnorm
    . next v ty mOp mApp tyold mVar =>
      injection Hnorm with H1 H2 H3
      subst H3
      intros x hin
      have : x ∈ Imperative.HasVarsPure.getVars (@Expression.Expr.fvar () v ty) := by
        simpa [Lambda.LExpr.LExpr.getVars] using hin
      simpa [Imperative.HasVarsPure.getVars] using this
    . next h =>
      exfalso
      cases Hnorm with
      | app _ _ Hn =>
        have := Hn IsOldPred.oldPred
        cases this with
        | fvar => exact absurd rfl h
    . next e1 e2 =>
      cases Hnorm with
      | app H1 H2 _ =>
      intros x hin
      have := List.mem_append.mp hin
      cases this with
      | inl h =>
        have : x ∈ Imperative.HasVarsPure.getVars e1 ∪ Imperative.HasVarsPure.getVars e2 :=
          List.mem_union_left _ h
        exact this.1 (fn_ih H1 h)
      | inr h =>
        have : x ∈ Imperative.HasVarsPure.getVars e1 ∪ Imperative.HasVarsPure.getVars e2 :=
          List.mem_union_right _ h
        exact this.2 (e_ih H2 h)
  | abs m ty e ih =>
    intros Hnorm
    cases Hnorm with
    | abs Hn => exact ih Hn
  | quant m k ty tr e trih eih =>
    intros Hnorm
    cases Hnorm with
    | quant Ht He =>
    intros x hin
    have := List.mem_append.mp hin
    cases this with
    | inl h => exact Or.inl (trih Ht h)
    | inr h => exact Or.inr (eih He h)
  | ite m c t e cih tih eih =>
    intros Hnorm
    cases Hnorm with
    | ite Hc Ht He =>
    intros x hin
    rcases List.mem_append.mp hin with h | h
    . exact Or.inl (cih Hc h)
    . rcases List.mem_append.mp h with h | h
      . exact Or.inr (Or.inl (tih Ht h))
      . exact Or.inr (Or.inr (eih He h))
  | eq m e1 e2 ih1 ih2 =>
    intros Hnorm
    cases Hnorm with
    | eq Ha Hb =>
    intros x hin
    rcases List.mem_append.mp hin with h | h
    . exact Or.inl (ih1 Ha h)
    . exact Or.inr (ih2 Hb h)