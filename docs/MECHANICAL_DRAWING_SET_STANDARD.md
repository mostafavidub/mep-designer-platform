# Mechanical Drawing Set Planning Standard

Rule Book version: 4.2 — Mechanical authority pipeline v18.3 / Final Engineering QA

## Governing principle

The customer-facing mechanical drawing count is the number of approved mechanical drawings actually issued. It is not the number of systems, architectural levels, model-space networks, or internal CAD views.

The mandatory flow is:

Architecture Upload -> Multi-Evidence Analysis -> Project Mechanical Model -> Mechanical Questions -> System Effective Levels -> System-Specific Typical Analysis -> Drawing Manifest -> Proposal -> Approval -> Frozen Approved Manifest -> CAD Generation -> Final Engineering QA -> Issue.

## Architectural direction and presentation cleanliness

The architectural north symbol is the sole directional authority. The engine must detect its vector from the owning architectural plan and preserve that original symbol through the same plan transform. It must never invent, default, or draw a second north arrow. Missing north evidence or any generated/source directional conflict blocks release.

Architectural office print frames, inner white sheet borders, legacy footer/title strips, duplicated plan subtitles and scale bands are source presentation furniture—not building geometry—and must be removed from every issued plan. Only the EngiTools outer sheet frame and compact bottom title block may remain. Removal must be evidence-based; walls, doors, windows, shafts, grids, dimensions and unknown architectural geometry remain protected. Exact-file reopen QA must reject any surviving source frame, duplicated subtitle band or generated second north symbol.

## Project Mechanical Model (PMM)

Before sheet planning, the project must have one canonical PMM shared by Planner, QA and the CAD migration path. It carries detected/candidate levels with evidence and confidence, rooms/spaces, fixtures, equipment, shaft candidates, system-specific scope, Typical groups and the ordered Drawing Manifest.

No downstream component may silently rediscover and replace PMM decisions.

## Multi-evidence Level Detection

A real level must not disappear merely because room labels or fixture blocks are missing. Detection combines explicit Persian/English plan titles, basement/ground/mezzanine/roof/penthouse terminology, source/container identity, nearby architecture evidence, spatial separation and geometry/room-pattern evidence.

Explicit mezzanine/commercial-balcony plans are preserved even when their room labels are incomplete. Weak orphan reusable block titles remain `candidate_level` and are not activated without corroboration. A level restored from title evidence alone cannot become Typical automatically.

## Fixture & Equipment Detection

Detection is multi-signal: block name, typed layer, nearby text, compact geometry signature and spatial context. Text-only evidence remains candidate-level. Persian and English aliases are supported.

A confirmed wet level with zero high-confidence fixtures is a hard pre-design evidence condition. Design may continue only after valid CAD evidence or a quantified user-confirmed fixture schedule resolves it. A bare confirmation is not sufficient.

## System-specific Typical Floor

Typical equivalence is evaluated separately for water, sanitary/vent, heating, cooling, gas and ventilation. Geometry similarity alone is insufficient; the relevant wet core, shaft, fixture/consumer distribution, equipment/load positions and routing topology must also match. When uncertain, keep separate sheets.

CAD must never expand members of an approved Typical group into extra layouts.

## Approved Drawing Manifest contract

The Planner is the only authority for sheet composition. It emits a versioned manifest with unique `manifest_id`, exact `total_sheets` and ordered sheet records containing code, family, represented levels, pattern, Typical status and Special status.

Approval freezes that manifest. CAD iterates only the frozen approved manifest. Missing, extra, duplicate, reordered or renamed issued layouts are a hard failure. A generic `M-RISER-CALC` sheet must not be inserted unless explicitly present in the approved manifest.

## Authority-separated families

Default approval families remain separated:

1. Water supply.
2. Sanitary + vent.
3. Heating.
4. Cooling/HVAC + condensate.
5. Gas.
6. Ventilation/exhaust.
7. Roof/rainwater.

Different families are not merged merely to reduce the customer-visible count.

## Special Sheet rule

A Special Sheet must contain a genuinely distinct drawing role. A renamed duplicate of a base-plan viewport is not acceptable.

- Water riser: vertical schematic, branch/level connections and isolation information.
- Water equipment: service/meter/control/primary equipment/distribution arrangement.
- Sanitary riser/detail: stack, cleanout, trap and vent information.
- Cooling equipment: independent equipment/roof coordination when applicable.
- Rainwater: roof drainage geometry and rainwater layer visible.
- Parking ventilation: issued only for actual enclosed-parking scope.

## Water + Sanitary requirements

Water must contain connected cold/hot networks, branch/trunk geometry, sizing tags and isolation. Sanitary/vent must contain connected branches, stack/discharge logic, slope and pipe-size tags plus cleanouts. Room evidence may create explicitly labelled rule-based connection zones but may not be presented as detected fixtures.

The water/sanitary engine fails closed when its applicable network checks fail.

## Gas requirements

Applicable gas scope requires resolved connected load, flow, inlet pressure and main DN, plus connected network, meter, regulator and terminal shutoff. Where architecture lacks a gas block but a resolved appliance schedule and observed kitchen exist, a terminal may be `RULE-BASED PROPOSED` with explicit provenance. A lone gas line is not an acceptable issued design.

## Heating / Cooling / Ventilation requirements

Heating supply and return must be connected networks. Cooling and condensate must be present with resolved cooling/heating load basis and per-conditioned-space allocation. Roof scope may carry explicit outdoor-equipment coordination.

### Split-AC visual contract

Every conditioned-space indoor unit uses the standard labeled `ENGI_AC_INDOOR` block and has a readable IDU tag, capacity callout, leader, airflow arrow, refrigerant route and condensate route. Every roof outdoor unit uses the labeled `ENGI_AC_OUTDOOR` block and identifies its served IDU. Release QA checks exact block identity, linked counts, minimum plotted pixel dimensions and a separately rendered preview for every Split-AC sheet. Entity or layer presence by itself never proves visual completeness.

Ventilation requires an exhaust network, resolved airflow basis, make-up-air endpoints and safe discharge endpoints.

## Roof / Rainwater requirements

Roof drainage requires detected/coordinated roof drains, connected route to a rainwater stack, design basis for roof area/rainfall/drain count/flow/DN and canonical output on `ENGITOOLS-M-ROOF_RAINWATER`. Any rainwater sheet that hides the actual rainwater geometry fails QA.

## Final Engineering QA — fail closed

No mechanical revision may be issued unless all applicable checks pass:

- approved manifest exact order and count;
- base technical quality = 10/10;
- compact-output QA = PASS;
- DXF audit has zero errors;
- required engineering content exists on every applicable family layer;
- water/sanitary engine = PASS when applicable;
- gas engine = PASS when applicable;
- HVAC/ventilation engine = PASS when applicable;
- rainwater engine = PASS when applicable;
- every Special Sheet contains substantive independent paper-space content.

The automated output still requires professional engineering review and does not claim statutory approval by itself.

## Release-blocking benchmarks

### 13-sheet authority-equivalent regression

The maintained automated benchmark uses a synthetic authority-equivalent project containing one effective occupied level plus roof, all six occupied-level families and the required system-specific Special roles. Planner must freeze exactly 13 sheets and the production CAD wrapper must issue exactly those same 13 layouts with Final Engineering QA = PASS.

This is explicitly a synthetic regression equivalent; it is not represented as a re-run of a customer binary file unless that binary is separately provided to the test environment.

### 21-sheet reference-profile regression

Three independent non-Typical occupied levels plus roof, six separated occupied-level families, water riser, cooling roof/equipment and dedicated roof/rainwater must freeze and issue exactly 21 layouts. `M-RISER-CALC` must not appear.

### Typical-floor regression

The system-specific Typical suite remains release-blocking and verifies that system evidence can keep one family separate while allowing another to consolidate, and that title-only restored levels never become Typical.

## Production release gate

Every Rule Book change must be paired with code implementation and automated regression coverage. Railway pre-deploy runs `compileall`, the full unittest suite and application import. A failed test blocks deployment. Production healthcheck is `/system_health` and must return HTTP 200.
