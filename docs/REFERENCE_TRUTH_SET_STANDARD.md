# Reference Truth Set Standard

## Purpose

A Reference Truth Set stores reviewed engineering facts from an approved/held-out reference drawing without storing the customer drawing itself in Git. It is evidence for post-seal comparison, regression analysis, and rule calibration; it is never an input to blind generation.

## Non-negotiable rules

1. Private/customer DXF bytes must not be committed to Git.
2. Every truth set must identify the project/test case, schema, purpose, evidence status, and source-hash status.
3. A reference may be opened only after the candidate output has been blind-sealed when the run is classified as independent/blind.
4. Semantic facts must distinguish observed reference values from authority/manufacturer facts. A capacity label is not an exact manufacturer model; a drawn gas line is not utility approval.
5. Missing source binaries or unverified hashes remain `INPUT_REQUIRED`; a SHA256 must never be guessed, shortened, or copied from an unrelated file.
6. A truth set must include explicit non-claims for evidence the source does not establish.
7. A truth set may calibrate a general rule only through a reviewed Rule Book/SWCIS change. Project-specific geometry or routes must not be copied into generalized generation logic.

## Minimum contract

A machine-readable truth set contains:

- `schema`
- `project_id` or stable test-case identifier
- `purpose`
- `privacy_policy`
- `source.reference_file_sha256`
- `source.hash_status`
- `facts`
- `evidence_status`
- `non_claims`

## Blind-use contract

The generation path must not read `standards/golden/*.reference-truth.json` before sealing. The allowed sequence is:

`architecture/project inputs -> generation -> QA -> blind seal/hash -> open held-out reference -> semantic comparison -> strict score`

Any pre-seal reference access contaminates the blind run and is a hard FAIL.

## Current Project 10 baseline

`standards/golden/project-10.reference-truth.json` is the semantic held-out baseline for the Fasihi mechanical reference. Its semantic facts are reviewed evidence. Its binary SHA256 remains `INPUT_REQUIRED` until the exact reference binary is available and independently hashed.
