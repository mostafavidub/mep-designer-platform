# MEP Designer Platform

Production is a **Single Living System** identified automatically by its Git
commit and dependency hashes. The CAD service starts only from
`cad_engine.main:app`; `/version` and `/system_health` publish the same immutable
build identity. Git commits/tags are the release history and rollback mechanism.

Architecture-first MEP design web application. Users upload architectural DXF files; the platform extracts and computes every engineering input that can be derived reliably from the plan, then asks only unresolved project facts or owner decisions.

Current runtime:
- Dynamic unresolved-only questionnaire
- Architecture-derived preliminary electrical/mechanical calculations
- Discipline-isolated Electrical and Mechanical CAD outputs
- Automated pre-deploy unit tests

CAD generation runs through the internal CAD Designer service configured with `CAD_DESIGNER_URL`.

All generated engineering calculations and drawings remain preliminary and require professional verification before construction use.
