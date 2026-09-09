# Submission QA and Golden Regression Standard

Submission Ready is fail-closed. The engine requires explicit numeric evidence
equal to zero for all ten release invariants: route warnings, structural and MEP
clashes, unapproved penetrations, gravity violations, equipment without an
official manufacturer basis, manufacturer-limit violations, missing mandatory
details, plan/riser/schedule mismatches and unreadable annotations.

An absent, negative, boolean or nonnumeric check is `INPUT_REQUIRED`. Any
positive count is FAIL. A phase label alone is never evidence of compliance.

The permanent regression cohort is projects 1, 3, 4, 6, 7, 8 and 10. Every case
must be generated from architecture-only inputs while references are closed,
hash-sealed, reopened exactly, and compared only after the seal. Duplicate or
missing cohort members, mutated seals and invalid access order block release.

Comparison has three independent gates: locked semantic presence, governed
artifact inventory, and numeric values with an explicit tolerance and Rule ID.
Regression, deletion or missing evidence blocks. Private drawings and source
filenames are not persisted; only hashes, semantic records and reproducibility
metadata may enter repository baselines. If an external private source is not
available with independent evidence, its real comparison remains
`INPUT_REQUIRED`/`PRE_SUBMISSION` and is never reported as PASS.
