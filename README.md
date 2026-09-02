# MEP Designer Platform

Active production release: **18.4.1**. The CAD service starts from
`cad_engine.main_v18:app`; `/version` and the website `/system_health` response
publish the same authoritative component-version manifest.

Architecture-first MEP design web application. Users upload architectural DXF files; the platform extracts and computes every engineering input that can be derived reliably from the plan, then asks only unresolved project facts or owner decisions.

Current runtime:
- Dynamic unresolved-only questionnaire
- Architecture-derived preliminary electrical/mechanical calculations
- Discipline-isolated Electrical and Mechanical CAD outputs
- Automated pre-deploy unit tests

CAD generation runs through the internal CAD Designer service configured with `CAD_DESIGNER_URL`.

All generated engineering calculations and drawings remain preliminary and require professional verification before construction use.
