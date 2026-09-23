# Version matrix (from warm-up JSONL, synced Aug 17 2026 Space release)


| Problem | Corpus | Versions |
|---|---|---|
| `CallElimCorrect.substOldPostSubset` | strata | v4.26.0 |
| `CallElimCorrect.extractedOldExprInVars` | strata | v4.26.0 |
| `Core.InitsUpdatesComm` | strata | v4.29.1, v4.27.0, v4.26.0 |
| `fundamental_theorem_of_variational_calculus'` | physlib | v4.32.0 |
| `Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema` | physlib | v4.32.0 |
| `FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time` | physlib | v4.32.0 |
| `Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress` | cslib | v4.33.0-rc2, v4.32.0, v4.31.0 |
| `Cslib.SKI.parallelReduction_diamond` | cslib | v4.33.0-rc2, v4.32.0, v4.31.0, v4.30.0 |
| `Cslib.CCS.bisimilarity_congr_choice` | cslib | v4.33.0-rc2, v4.32.0, v4.31.0 |
| `Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius` | arklib | v4.31.0, v4.30.0, v4.29.0, v4.28.0 |
| `Binius.BinaryBasefold.fold_advances_evaluation_poly` | arklib | v4.31.0, v4.30.0, v4.29.0 |
| `interleaved_affine_gaps_imply_tensor_gaps` | arklib | v4.31.0, v4.30.0, v4.29.0 |
| `putnam_1964_a4` | putnambench | v4.25.0, v4.26.0, v4.27.0 |
| `putnam_1964_b2` | putnambench | v4.25.0, v4.26.0 |
| `putnam_1995_a3` | putnambench | v4.25.0, v4.26.0, v4.27.0 |

Patch releases are **not** always unifiable in one Lake project. Local layout:

| Dir | Toolchain | Corpora |
|---|---|---|
| `projects/v4.29` | `v4.29.0` | Physlib + ArkLib |
| `projects/v4.29.1` | `v4.29.1` | Strata |

The Space upload filter now rejects line-start `def`/`abbrev`/`instance`/…
auxiliaries (and `#count_heartbeats` in submissions). Heartbeat refs exist
for all 15 warm-up problems in `benchmark_heartbeats.jsonl`.
