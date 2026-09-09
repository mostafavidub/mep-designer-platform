# Mechanical Reference Corpus Standard

## Status

This standard governs the owner-supplied architecture-to-mechanical reference corpus registered on 2026-09-09. The machine-readable inventory is `standards/test-suites/mechanical-reference-corpus.json`.

The corpus is **comparison and calibration evidence**, not a generation database. Source DXF bytes and customer filenames stay outside Git. Git stores only privacy-safe project IDs, verified SHA-256 hashes, reference inventories, and semantic observations.

## Corpus roles

The current clean architecture/mechanical pairs are Projects 1, 3, 4, 5, 6, 7, 8, 9, and 10. Project 10 (`fasihi`) is the primary development/debug benchmark. Project 12 is reference-only because its architecture background is embedded in the mechanical drawing rather than supplied as a clean independent architecture input. Project 11 is excluded from the mechanical corpus because the supplied drawing is electrical/non-mechanical evidence. Project 2 was not supplied.

To reduce implementation overfitting, the inventory freezes these roles:

- Development/reference extraction: 1, 3, 5, 6, 8, 10.
- Validation only: 4, 7.
- Reference-sealed evaluation: 9. After this freeze, Project 9 may be scored but must not be used to tune rules or constants.
- Reference-only support: 12.
- Excluded from mechanical regression: 11.

Because all supplied reference drawings have already been inspected enough to classify and inventory the corpus, **none of these projects is represented as a strictly unseen blind project**. The split protects future tuning integrity; it does not retroactively create strict blindness.

## Required comparison order

For a paired project, the intended regression order is:

`Architecture input -> generate with engine + authoritative project inputs -> seal input/output hashes -> unseal mechanical reference -> semantic/artifact score and diff`

A missing reference run must never be reported as PASS. Optional private reference absence does not block ordinary publication, but an engineering-quality claim based on that reference requires an actually executed comparison.

## What may be learned from references

Reference drawings may identify candidate behaviors such as recurring annotation conventions, drawing families, network materialization expectations, and recurring engineering decision points. Repetition across several drawings is useful evidence that the engine should investigate a capability.

Reference recurrence is **not engineering authority**. A value seen repeatedly in references cannot become a global numeric default merely because it is common. Numeric sizing, load, airflow, pressure, slope, equipment selection, rainwater, and similar engineering decisions require applicable code/standard/manufacturer evidence or explicit authoritative project input.

Every extracted numeric list in the corpus therefore carries `REFERENCE_OBSERVED_NOT_DESIGN_RULE`, and every cross-project pattern carries `CROSS_PROJECT_REFERENCE_PATTERN_NOT_DESIGN_RULE` with `promotion_status = CANDIDATE_ONLY`.

## Promotion into the Mechanical Engine

A candidate behavior may be promoted only when all of the following are true:

1. The behavior is expressed as a general engineering/output requirement rather than a project-specific answer.
2. Numeric engineering behavior has independent authority from an applicable rule, standard, manufacturer record, or authoritative project input.
3. The promoted behavior receives a Rule ID and an explicit Source -> PMM -> Calculation/Topology -> Drawing -> QA traceability chain where applicable.
4. Focused positive and fail-closed negative tests exist.
5. Development and validation projects pass without using reference values as generation inputs.
6. Project 9 is scored only after the change is frozen and is not used for subsequent tuning of that change.

If any authoritative input is missing, the engine must expose `INPUT_REQUIRED`/pre-submission state rather than infer a customer-specific number from the corpus.

## Project 10 / Fasihi

Project 10 is intentionally a development/debug reference. Its architecture and mechanical hashes are verified in `standards/golden/project-10.reference-truth.json`. Reviewed Fasihi facts may be used to explain a mismatch after a generated artifact exists, but they may not be injected into generation as hidden constants. A change that improves Fasihi while degrading validation/evaluation evidence is not a successful generalization.

## Acceptance evidence for this corpus contract

The repository tests enforce cohort disjointness, verified hashes for clean pairs, Project 10 hash consistency, privacy-safe metadata, exclusion of Projects 11/12 from paired generation regression, and the rule that cross-project recurrence cannot self-promote into an engine rule.
