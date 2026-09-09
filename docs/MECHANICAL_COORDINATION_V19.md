# Mechanical pre submission release 19.1.0

Release 19.1 uses an architecture-only Pre-Submission operating profile until
Structural/RCP inputs become available. Missing structural data does not stop
draft generation, but the output is permanently marked `PRE_SUBMISSION`,
`NOT_COORDINATED`, and `NOT_MANUFACTURER_CONFIRMED`. It cannot be represented
as Submission Ready. Malformed supplied data and real QA failures remain
fail-closed.

1. Structural/RCP coordination stores source-hashed beams, columns, slabs,
   ceilings, shafts, service zones and forbidden zones in a shared 3D datum.
   The 2.5D router compares orthogonal candidates across permitted elevations
   and validates clashes, penetrations, clearance and gravity slope.
2. Manufacturer selection accepts only revisioned official datasheets. It
   checks calculated capacity, dimensions, connections, clearance, maximum
   route/elevation, pump head and fan flow. Missing evidence yields a Design
   Envelope marked `PRE_SUBMISSION`, never a fictional model.
3. Details contain executable geometry, dimensions, fittings, material,
   clearance and tags. Each active system declares mandatory detail families;
   missing parameters or families remain `INPUT_REQUIRED`. Risers are generated
   from the network graph, enforcing `Plan ID = Riser ID = Calc ID = Schedule ID`
   with zero mismatch. Plan annotations reference network-edge identities and
   enlarged plans require an explicit source plan, bounds and scale.
4. Golden projects 1, 3, 4, 6, 7, 8 and 10 are generated blind and hash-sealed
   before any reference comparison. Post-seal comparison produces separate
   semantic, artifact-inventory and numeric diffs. Numeric tolerances require a
   Rule ID; removed locked semantics, changed/missing governed artifacts,
   ungoverned tolerances and numeric regressions block the gate. Thresholds are
   score >= 70, score drop <= 0, and pass rate = 100%.
5. Heating issue output is derived from room heat loss, declared supply/return/
   room temperatures, and an exact official radiator record. Selected sections,
   output and dimensions propagate to plans/details/schedules; heating mains use
   cumulative selected output. Package selection checks space heating, DHW and
   simultaneous combined demand.
6. Gas issue output requires an official appliance record and project gas basis.
   Every segment carries gas flow, equivalent length, selected DN and Calc ID;
   meter, regulator, appliance shutoff, flue and combustion-air evidence are
   mandatory. Missing external values remain `INPUT_REQUIRED`.
7. Split AC issue output uses explicit room component loads, zone diversity and
   official IDU/ODU records. Capacity margin, airflow, refrigerant sizes, route
   length, elevation, condensate and connected ratio must all reconcile.
8. Exhaust issue output covers every applicable room using declared ACH/CFM and
   duct-path ESP. A fan must satisfy both flow and ESP; any unserved room blocks
   release.
9. Roof rainwater output requires actual roof/catchment geometry, low points,
   drains, emergency overflows, stacks and rainfall basis. Every catchment flow
   and DN is calculated; a roof coordination schematic cannot pass this gate.
10. Risers are hashed projections of the plan graph. Only typed architectural
    levels are accepted; `DETAIL` sheets are rejected and plan/riser/calc/
    schedule identity mismatch remains zero.
11. Manufacturer records contain the full engineering selection dataset and an
    official revisioned document hash. Only semantic fields and hashes are
    retained; reseller or incomplete records cannot enter the final database.
12. Final radiator, ODU and sanitary details are system-specific executable
    geometry bound to Plan/PMM/Calc/Catalogue identities. Missing installation
    components or manufacturer-dimension mismatch blocks documentation.
13. The calculation book records load, selection, margin, manufacturer limits,
    route/elevation and identity for every equipment tag. Pump and fan operating
    duties must pass their supplied manufacturer curves.
14. Annotation placement is priority-, collision- and print-scale-aware. Dense
    regions create source-bound enlarged plans; unreadable or colliding labels
    block release.
15. Submission Ready requires explicit numeric zero evidence for route warnings,
    structural clashes, MEP clashes, unapproved penetrations, gravity
    violations, equipment without manufacturer basis, manufacturer-limit
    violations, missing details, plan/riser/schedule mismatches and unreadable
    annotations. Missing evidence is `INPUT_REQUIRED`; nonzero evidence is FAIL.
16. The locked seven-project cohort is unique and complete. Every case records
    architecture-only blind generation, an immutable seal and strictly later
    reference access. Semantic, artifact and governed numeric differences are
    blocking, and persisted source filenames/private drawings are prohibited.
17. Independent engineer redlines are deterministically classified as
    project-specific, rulebook deficiency or engine bug. Project-only findings
    cannot train shared rules; reusable findings require governed regression
    evidence, and every open major/critical redline blocks acceptance.
18. Final acceptance enforces zero critical defect counts, route efficiency
    >=90%, equipment placement >=90/100, detail completeness >=95%, every main
    plan >=85/100 and package average >=90/100. Missing measurements remain
    `INPUT_REQUIRED`; targets are never used as fabricated measured scores.

The repository regression cases verify this protocol with synthetic semantic
baselines. A private-project comparison is reported only when the exact external
source and its independently captured hash are available; otherwise its status
is `INPUT_REQUIRED`/`PRE_SUBMISSION`, never PASS.

Private customer drawings and generated customer DXFs are never committed.
Only hashes, semantic metrics and reproducibility metadata may enter baselines.

## Production runtime authority

The website stamps every mechanical design request with the complete active
version manifest and PMM v2 input contract. The active `main_v19` service
rejects a stale or missing stamp, runs all v19 preflight phases, and only then
invokes the stable drawing compositor. Every successful report returns the
versions actually executed; the website rejects the artifact if analysis,
design or verification differs from its active version.
