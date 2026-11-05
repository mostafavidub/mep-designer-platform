# Executable Rulebook standard

Status: governed by SWCIS 5.17.0 and MEP-RAIN-RULEBOOK-001.

The canonical shared schema is `data/rulebook/schema/executable_rule.schema.json`.
Each discipline module owns one authoritative definition for a stable Rule ID.
An executable rule records its owner, version, source edition/clause/page and
source-entry identities, applicability and exceptions, required inputs with
units and authority, deterministic design action and validator, cross-references,
and output evidence. Definitions, guidance, dependencies, operative rules and
documented non-applicability are different classifications.

`UNKNOWN` applicability is `INPUT_REQUIRED`; it is never `NOT_APPLICABLE` or
`PASS`. A rule record is not evidence that its obligation was met. LLM proposals
are non-authoritative and cannot replace a fixed parameter, applicability result,
source fact, official design basis, product approval, structural approval,
physical execution test or permit decision.

The first module is `mechanical.rainwater.iran`. It maps every entry in the
reviewed M4-1396, M6-1398 and M16-1396 handoff to an executable rule, definition,
guidance, dependency, documented non-applicability, or explicit unresolved
control. Unresolved controls block a complete statutory-coverage claim; they do
not block unrelated Mechanical systems or prevent a clearly marked DRAFT
rainwater artifact whose unmet requirements are visible.

The module imports architectural roof/shaft and boundary evidence, structural
rain-load and ponding review, and fire penetration requirements by stable
dependency identity. It does not duplicate or invent those approvals. The PMM,
calculations, generated DXF, reopened-artifact QA and Persian diagnostics carry
the same module dependency identity and per-rule outcome. Any source, mapping,
module or rule-version change invalidates cached evaluation.

Mechanical rainwater module `1.1.0` adds four executable controls. The complete
printed Appendix 7 vertical and SI horizontal tables are immutable governed data;
the DN250/4% row remains exactly `15984 m2, 112.52 L/s` and is explicitly marked
as a preserved print anomaly. Appendix sizing uses horizontal roof projection,
adds one half only of a proven contributing wall, counts each upstream level
transfer once, applies `25.4 / i_mm_h`, and selects vertical and horizontal DN
independently without interpolating an unprinted slope. The generated plan must
carry a calculation-linked hydraulic schedule.

Material marks and certificates are different evidence: permanent manufacturer
and approved-standard marks never substitute for a competent-body certificate,
pressure suitability, or product identity. Buried gravity segments require a
model-derived schedule and trench detail with continuous shaped bedding,
balanced 150 mm maximum lifts, and conditional rock/weak-soil dimensions.
Certificate, inspection-before-covering, physical test, permit and structural
approval evidence remains external and may not be fabricated by software.

Module `1.2.0` adds discipline-owned boundary contracts without duplicating
authority. Architecture owns discharge destination, property-boundary and
nuisance constraints; discharge to adjacent property, public way or a facade is
rejected, while surface discharge inside the project property remains dependent
on an actual permit identity. Structural owns permanent-load coordination; actual
empty and water-full masses and support-reaction identity are scheduled and must
carry an external structural approval reference. The Mechanical plan consumes
both contracts and materializes destination and structural-load schedules, but
cannot issue either the municipal permit or structural approval.

Module `1.3.0` adds architecture-owned, per-entity controls for waterproofing
interfaces and basement openings. Applicability is derived from verified surface
and opening geometry; only a source-verified low-exposure balcony or verified
absence of basement openings may produce an exception. The rainwater designer
materializes the corresponding upstand, sealed penetration and runoff-interceptor
details without treating software output as construction inspection or approval.

Module `1.4.0` adds per-route shaft access and private-unit intersection
controls plus suspended-ceiling clear-height and independent-support controls.
Missing zone, access or elevation geometry is `INPUT_REQUIRED`; a foreign
private-unit intersection passes only after an identified eligible reroute is
materialized. A ceiling exception requires verified absence of an adjacent
suspended-ceiling interface.

Module `1.5.0` adds a pitched-roof-only property-boundary and safety contract.
It computes the downslope edge distance from source geometry using the M4
building-group threshold, requires external group-8 special criteria, and
materializes snow/ice retention and worker-anchor evidence. It does not reuse
the flat-roof two-percent surface rule or any pipe-slope threshold.

Module `1.6.0` implements only direct M4 drainage obligations for exterior
egress, semi-open/open spaces, sunken courtyards and parking. Per-space polygon,
slope vector, drain, route and destination evidence is required. Public-way
discharge, ponding, a roofed sunken courtyard and unprotected ground-floor
parking runoff entry fail; an alternative parking measure remains dependent on
an actual authority approval identity.

Module `1.7.0` adds per-interface M16 installation protection. Foundation and
structural penetrations require a sleeve/clearance detail and valid structural
approval provenance; corrosion, burial and impact exposures require protection;
elevator-shaft routing is rejected; foundation-adjacent trenches, restored
assemblies and outlet grates are explicitly evidenced in the generated plan.

Module `2.0.0` completes the entry-level M16 review. It adds stage-aware drawing
and closeout evidence, geometric roof-equipment overflow routing, gravity,
material, joint and support controls, and conditional protection for demolition,
potable makeup components and potable tanks adjacent to rainwater routes. Final
inspection evidence is requested only at final inspection and is never fabricated
at design stage.

Module `2.1.0` records the M4/M6 entry review in
`source_review_m4_m6.json`. A clause is closed only when a concrete producer,
validator/calculation/geometry check and test are all identified. A `PASS`
owner-module manifest with valid provenance is a fail-closed dependency input,
not proof that the underlying clause has been implemented. Clauses lacking that
implementation chain remain `UNRESOLVED_CONTROL` and block final compliance.

Module `2.2.0` closes M4 clauses 4-5-1-7-7/8, 4-9-5-1 and 4-9-9-1-1
with a geometric roof-access control. It computes the four-storey, 33-percent
slope and no-use exceptions, verifies headhouse area against the stair enclosure,
and requires a continuous polygon enclosing an accessible roof with a parapet at
least 1.10 m high. The chosen access and dimensions are rendered into the DXF.

Module `2.6.0` extends that geometry to per-edge continuity and guarded openings,
adds exact landing/threshold limits, computes the M6 rain-on-snow `W/15` boundary
and 0.25 kN/m2 surcharge exclusions, and schedules minimum roof, service walkway,
equipment-room and fixed-ladder live loads. Product or structural approval remains
external evidence; deterministic applicability and boundary calculations run locally.

Module `2.7.0` requires real guard geometry across parapet openings and implements
material-specific M16 standards and joints for cast iron, galvanized steel, U-PVC,
PP and HDPE. Burial markings, the PP six-metre water-column limit, U-PVC cold
adhesive temperature, and hubbed cast-iron lead dimensions are deterministic;
equivalent standards and manufacturer exceptions still require external approval.

Module `2.8.0` adds exact M16 material/orientation support-installation controls:
cast-iron vertical base bearing below the lowest elbow, hub/joint-adjacent clamps,
buried horizontal cast-iron sand bedding, galvanized fixed/guided and pendular
movement, insulated-clamp steel liners of at least 1.5 mm by 300 mm, and plastic
horizontal clamp/support material and movement. The generated DXF carries the
same support-installation schedule. Local live-E2E mutation is fail-closed on
child PID, unique nonce, fixture identity and isolated database identity; an
occupied 8080 port leaves that test BLOCKED / NOT RUN.

Module `2.9.0` executes the M16 potable-outlet air-gap table when a potable
outlet discharges over an open rainwater receptor. It computes fixed near/far
wall minima by outlet class, two/three-times-effective-diameter minima above
25 mm, and the 100 mm potable-storage minimum, then dimensions the selected
case in the generated DXF.

The full-text review of M16-001 through M16-009 classifies those nine entries as
scope, purpose, legal hierarchy, referenced-standard precedence, or M21/M22
owner-module dependencies. They remain non-passing context records and are not
invented as duplicate project controls; their concrete downstream obligations
continue to be enforced by the clause-specific material, documentation and
installation rules.

Module `2.15.0` expands the seven printed LRFD base combinations into 25
Lr/S/R and signed ±W/±E alternatives relevant to roof rain loading. It only
combines declared, dimensionally compatible force, moment, stress or pressure
effects in a common unit and uses an absolute governing envelope only when a
symmetric capacity mode is explicitly declared. Unsupported effect/unit or
asymmetric-capacity cases remain `INPUT_REQUIRED`. Structural analysis identity
remains an external professional dependency.
The same module expands the ten printed ASD combinations into 24 signed and
alternative cases and prohibits any allowable-stress increase. It also derives
primary-blockage rain load from actual undeformed-roof and secondary-inlet
elevations plus the hydraulic design head as `R = 0.01(ds + dh)`. A
ponding-susceptible bay requires a converged, stable iterative
deformed-geometry analysis; an approval label alone is not analysis evidence.
The ponding response requires at least two numbered solver iterations, a
numeric residual within a declared positive tolerance, reconciled final water
surface/deformed-low-point depth, and structural-engineer approval bound to the
same structural-model SHA-256. Roof slope alone never proves immunity. The
structural owner module also recomputes `Pr = Is*Cn*Ch*Cs*Ps`, snow unit weight
and balanced snow depth and checks exposed-roof classification against actual
rooftop-obstruction geometry.
