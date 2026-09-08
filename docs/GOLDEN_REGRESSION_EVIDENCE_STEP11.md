# Step 11 — Seven-Project Golden Regression Evidence Integrity

Step 11 removes the release bypass in which a literal `{"status":"PASS"}` or `MECHANICAL_V19_GOLDEN_STATUS=PASS` could satisfy the v19 Golden phase without proving the locked seven-project regression.

## Locked release cohort

The release cohort remains exactly projects `1, 3, 4, 6, 7, 8, 10`, using `standards/golden/seven-project-v19.baseline.json`. Cohort membership, baseline bytes and thresholds are release inputs; missing, duplicated or substituted cases block release.

## Release invariants

1. A status string/object alone is never Golden evidence. Missing full evidence is `INPUT_REQUIRED` at the Golden phase and the v19 release remains blocked.
2. `MECHANICAL_V19_GOLDEN_STATUS` no longer supplies release authority. Golden evidence must be explicitly passed in `_v19_input_contract.golden_result` or `_v19_input_contract.golden_release_evidence`.
3. Evidence schema is `seven-project-golden-release/2.0` and must contain the exact locked cohort, the SHA-256 of the repository baseline and all seven project cases.
4. Evidence is bound to the exact running build: `build_identity`, commit SHA, rulebook schema revision and PMM schema revision must match the current build.
5. Every case carries the SWCIS-required evidence fields: `input_hash`, `generator_version`, `rulebook_version`, `pmm_schema_version`, `output_hash`, `semantic_diff`, `artifact_diff` and `strict_score`.
6. Build identity is also stamped inside the blind output before sealing, so changing build metadata after the seal invalidates the output hash/seal.
7. The blind output must be sealed before reference access. The validator recomputes the seal and independently recomputes strict score from post-seal reference metrics instead of trusting a claimed score.
8. `semantic_diff.status` and `artifact_diff.status` must both be `PASS` for every case.
9. A `PRE_SUBMISSION` or `INPUT_REQUIRED` blind output, or an output with `submission_ready=false`, can never become strict release Golden evidence even if its architecture-only profile regression passes.
10. Strict regression is recomputed against the locked repository baseline. Every project must satisfy the minimum score, maximum allowed drop and 100% required pass rate.
11. The evidence object's claimed status/pass-rate are compared with recomputed results; disagreement is release-blocking.
12. Existing architecture-only preview artifacts under `artifacts/v19/` are not promoted to Step 11 release evidence. The current repository QA report explicitly labels them `ARCHITECTURE_ONLY_PRE_SUBMISSION`, `submission_ready=false`, while its strict submission regression is `FAIL`.
13. Step 11 validates evidence contracts; it does not fabricate current production results for the seven projects. A real release still requires generating and sealing all seven cases from authoritative inputs for the exact release build.

## Status policy

- `PASS`: complete locked cohort, current build/baseline binding, valid seals, project-ready blind outputs, semantic/artifact diffs PASS, recomputed strict scores PASS, and pass rate exactly 1.0.
- `INPUT_REQUIRED`: release evidence or current build identity is unavailable/incomplete.
- `FAIL`: evidence exists but is stale, tampered, incomplete/duplicated, pre-submission, mismatched to the baseline/build, or fails strict regression.

## Safety boundary

The Step 11 unit/CI fixtures prove the validator itself. They are not evidence that the real seven production/project inputs have been regenerated on the current build. The final release gate must keep those two claims separate.