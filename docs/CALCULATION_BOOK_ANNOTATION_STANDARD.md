# Manufacturer-aware calculation book and annotation-solver contract

Status: governed by MEP-SIZE-001, MEP-EQUIP-001 and MEP-SUBMIT-001.

## Calculation book

Every declared equipment tag requires a selection-check section connected to its
PMM and Calc identities. The section records calculated load, selected capacity,
selection margin, manufacturer/model, route length, elevation, manufacturer
limits and PASS/FAIL status. Missing or duplicate checks and calculations without
matching identities block publication.

Pump sections include the operating point and manufacturer pump curve. Fan
sections include CFM, ESP and the manufacturer fan curve. Interpolated curve
capacity must meet the required duty; a nominal equipment label is not evidence
of compliance.

## Annotation solver

Annotations are placed in priority order using print scale, minimum plotted text
height, leader targets, plan bounds, obstacles and collision clearance. The
primary plan must finish with zero annotation collisions and zero unreadable
labels.

When a dense region cannot be annotated legibly, the solver may create an
identity-bound enlarged plan with explicit source plan, bounds, scale and reason.
If enlargement is disabled or cannot resolve the labels, the gate fails with
`UNREADABLE_ANNOTATION`; increasing label count alone cannot satisfy QA.
