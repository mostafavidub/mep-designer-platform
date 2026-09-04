# EngiTools Mechanical Authority Release v15.2

> **Historical release record.** This document preserves the v15.2 acceptance
> contract. Production now runs platform 18.5.9 through `cad_engine.main_v18:app`;
> this record must not be used to identify the active runtime version.

This document is the production release checklist for the mechanical workflow.  It is project-driven: the exact number of sheets depends on project evidence and required systems; the Gonbad benchmark happens to resolve to 28 sheets.

## Engineering pipeline

- Architecture reconstruction and drawing-type classification
- Primary floor-plan / roof isolation; sections, elevations, furniture/lintel frames excluded from plan routing
- Fixture and equipment recognition
- Project model, design basis and system-requirement engine
- Calculation provenance contract: missing utility/envelope/manufacturer inputs remain INPUT_REQUIRED/PRELIMINARY
- Plan-aware topology and routing; no cross-plan physical connections
- Segment sizing and annotations
- Real-project acceptance, plan-isolation acceptance and output sanitization

## Equipment and HVAC representation

- Wall-mounted split indoor units hosted on and parallel to a detected architectural wall
- Airflow graphics, refrigerant/condensate connection notes and local callouts
- Roof outdoor-unit coordination and indoor/outdoor pairing
- Equipment schedule synchronization
- Radiator representation and preliminary load/selection provenance

## Authority-style documentation

- Adaptive project sheet manifest and authority-style numbering/titles
- Integrated A4 frame + compact bottom title block; no separate floating title box
- Drawing safe area and zero title-block overlap QA
- Architecture-derived north direction when detectable
- General notes, dynamic details, equipment schedule and plumbing riser
- Exact-file reopen QA and semantic duplicate-sheet QA

## Engineering enrichments

- Roof rainwater/catchment calculation with project rainfall input or INPUT_REQUIRED status
- Water-service / meter / storage / pump / check-valve / riser topology
- Pump Q/H calculation with utility-pressure provenance
- Gas connected-load/equivalent-length sizing against P.22 table with final utility/code verification requirement
- Exhaust airflow/CFM annotation by room-use basis

## Preservation and cleanup policy

- Imported architecture is preservation-first.
- Footer cleanup may remove only positively identified presentation artifacts.
- Walls, doors, windows, openings, shafts, grids, stairs, ramps, columns, structural boundaries, dimensions and unknown source geometry are not deleted merely because they lie in a subtitle/footer region.
- Full Architecture Preservation Gate is a separate hardening phase; until then, ambiguous source entities default to preserve.

## Production wiring

- `start_services.sh` launches `cad_engine.main_v15_2:app` for the CAD service.
- Mechanical `/design` requests route through the complete authority site orchestrator.
- Electrical remains on the existing preliminary rule-driven path and is intentionally unchanged by this release.
- `/mechanical_release` exposes the deployed machine-readable capability contract.
