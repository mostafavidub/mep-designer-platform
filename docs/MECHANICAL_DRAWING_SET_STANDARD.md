# Mechanical Drawing Set Planning Standard

Rule Book version: 2.2 — Multi-Evidence Level Detection + Project Mechanical Model

## Mandatory pre-generation stage

Mechanical CAD generation must not start before Drawing Set Planning and explicit user approval.

Flow:

Architecture Upload -> Architecture Analysis -> Multi-Evidence Level Detection -> Mechanical Questions -> Project Mechanical Model -> Effective-Level Analysis -> Typical-Floor Analysis -> Authority Submission Sheet Planning -> Drawing Set Proposal -> User Approval -> CAD Generation

## Project Mechanical Model — single project snapshot

Before sheet planning, the system MUST build one canonical Project Mechanical Model (PMM) and store it with the project analysis. The PMM is the machine-readable mechanical snapshot shared by the Planner, QA and CAD Designer migration path.

The PMM must contain, at minimum:

- detected architectural levels and their evidence/confidence;
- unresolved candidate levels that are intentionally not activated;
- per-level space/room counts;
- detected fixtures and equipment;
- detected shafts/vertical-service candidates;
- system-specific effective-level scope;
- verified Typical Floor groups;
- the ordered Drawing Manifest produced by the Planner.

PMM v1 remains a compatibility layer while consumers are migrated in guarded releases. Architectural evidence is enriched by Level Detection v3 and carried into the PMM so downstream components do not need to rediscover floors independently.

A PMM integrity diagnostic must be recorded whenever the planner total differs from the manifest length or when no architectural level is available. Unresolved weak title candidates are recorded as diagnostics but remain non-blocking in this release.

## Level Detection — mandatory multi-evidence rule

A real architectural level MUST NOT be deleted merely because room labels or fixture blocks are missing. Level detection must combine multiple evidence channels and retain provenance for every floor.

Accepted evidence channels include explicit architectural plan titles in Persian or English, common level titles such as basement/ground/mezzanine/roof/penthouse, source container identity, nearby architectural room evidence from the same CAD source, spatial separation of title/plan groups when coordinates are available, and geometry/room-pattern evidence produced by the architecture analyzer.

Every active level must carry `level_confidence`, `level_evidence`, and `level_detection_status` into the PMM.

### Strong explicit levels

An explicit architectural plan title in the submitted layout/model source is strong enough to preserve the level even when that individual plan contains no recognized room labels. This specifically includes mezzanines and commercial balcony/mezzanine plans. Such a restored level enters the active architectural level set, but it may not become a Typical Floor without independent high-confidence geometry/room evidence.

### Weak/orphan titles

A title found only in an isolated/reusable named block with no nearby architectural room evidence MUST NOT silently create an active floor. It must be retained as a `candidate_level` with lower confidence and its evidence. Candidate retention is mandatory so uncertain evidence is visible instead of silently discarded.

### Typical-floor safety

A level restored from title evidence alone has `typical_confidence = insufficient`. It can never be consolidated into a Typical Floor group solely from its title/name.

### Required regression cases

Release tests must cover at least:

- Ground + explicit mezzanine where the mezzanine has no recognized room labels: mezzanine remains active.
- A far-away orphan sample-title block: it remains non-active and does not increase deliverable count.
- Persian and English mezzanine/basement title variants.
- A title-only restored level cannot become Typical.
- Existing Typical Floor, roof classification, Planner and CAD regressions remain green.

## Governing customer-facing count

Formal definition:

Deliverable Mechanical Drawing Count = Number of Approved Mechanical Drawing Sheets.

It is not the sum of systems, levels, or scope items. The number displayed to the customer MUST equal the number of separate mechanical drawings/sheets actually issued for approval and delivery.

For the local Engineering Organization submission profile, different mechanical disciplines MUST NOT be merged merely to reduce sheet count. A combined internal CAD view is not the same thing as an approval deliverable.

Therefore the previous composition rule that merged water+gas, heating+cooling, or sanitary+rainwater into one customer-counted sheet is retired for the authority-submission profile.

## Authority-separated deliverable families

The default mechanical approval set is separated into these deliverable families:

1. Water supply — cold/hot water and associated water-supply equipment/schematic.
2. Sanitary + vent — sanitary drainage and vent.
3. Heating — heating distribution only.
4. Cooling/HVAC — cooling distribution, condensate and required equipment/roof sheet.
5. Gas — gas piping only.
6. Ventilation/exhaust — mechanical ventilation and exhaust only.
7. Roof/rainwater — dedicated roof drainage plan.

Riser, equipment, calculation and legend information must be placed inside the relevant system family unless a project/authority rule explicitly requires an additional dedicated sheet. A generic extra M-RISER-CALC sheet must not be added by default because it changes the approved deliverable count.

## Effective Levels

A system is active only on levels where that system has a real design requirement. Effective Levels must be determined per system from architecture and resolved project inputs.

- Cooling: conditioned levels. Required outdoor/equipment level is counted as a special cooling sheet when applicable.
- Heating: heated levels only.
- Water Supply: levels with plumbing consumers. Multi-level projects also receive the required water-supply riser/equipment/schematic sheet.
- Sanitary/Vent: levels with sanitary fixtures/drainage scope.
- Ventilation/Exhaust: levels requiring mechanical ventilation/exhaust.
- Gas: levels with gas consumers when gas is enabled.
- Roof/Rainwater: one dedicated roof drainage sheet where roof drainage is required.

A level must never be included just because it exists architecturally, except for a required system-specific special sheet. Where room labels are incomplete, an explicitly confirmed non-roof architectural level remains available to the conservative authority scope rather than being silently deleted.

## Typical Floor rule

Typical-floor detection remains mandatory, but it is system-specific and must never be used to combine different systems.

Two or more levels may share one Typical Floor sheet for a given system only when all relevant characteristics match:

- architecture geometry and room arrangement;
- wet-core location where relevant;
- shaft/vertical reference positions;
- fixture/consumer distribution;
- equipment/load positions;
- the system-specific routing pattern.

If any of these materially differs, separate sheets are required. The authority-submission profile is conservative: when Typical equivalence is uncertain, keep separate sheets.

## Benchmark projects

### Duplex reference — 21 sheets

Three independent non-typical occupied levels, separated system families, the water special sheet, the cooling equipment/roof sheet, and the dedicated roof sheet must produce exactly 21 approved mechanical sheets.

### Afsari reference — 13 sheets

Ground plus two verified identical typical floors, all six occupied-level families, no dedicated roof sheet, and one water riser/equipment special sheet must produce exactly 13 approved mechanical sheets. Repeated typical floors must be represented by one sheet per applicable family.

Both benchmarks are release-blocking regressions. They validate different architectural conditions; 13 is not a generic replacement for 21.

## Approved Drawing Manifest contract

The Planner is the only component allowed to determine sheet composition. It must emit a versioned manifest containing a unique manifest ID, exact `total_sheets`, and the ordered list of sheet codes, families, effective levels, Typical pattern, and special-sheet status.

Approval freezes that manifest as `approved_manifest`. The Proposal reads its count from this manifest. CAD must iterate the approved manifest, never the raw level list:

```python
for sheet in approved_manifest["sheets"]:
    create_sheet(sheet)
```

After DXF generation, expected codes and count must equal issued layout codes and count. Any missing manifest, duplicate code, changed count, or Proposal/CAD mismatch is a hard Generation Failed result; the revision must not be marked ready.

## Calculation principle

For each system family:

1. determine its Effective Levels;
2. apply verified system-specific Typical Floor consolidation only when allowed;
3. count one separate deliverable sheet per remaining system-level pattern;
4. add required system-specific special sheets;
5. add the dedicated roof/rainwater sheet where required;
6. do not add a generic combined riser/calculation sheet unless explicitly required.

Customer Deliverable Sheet Count = length of the ordered Approved Drawing Manifest.

The customer-visible count and the final CAD deliverable count MUST be the same semantic quantity.

## Proposal contract

The proposal must show:

- each deliverable system family;
- exact sheet count per family;
- level or Typical Floor represented by each sheet;
- any system-specific special sheet;
- exact total deliverable sheet count;
- approval state.

The UI must never present an internal combined-family count as the customer deliverable count.

## Approval Gate

The customer must approve the exact authority-submission drawing list before mechanical CAD generation starts. If the list changes, approval is invalidated and must be obtained again.
