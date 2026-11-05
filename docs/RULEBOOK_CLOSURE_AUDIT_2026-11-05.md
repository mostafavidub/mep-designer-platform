# Mechanical Rulebook closure audit — 2026-11-05

This report belongs only to `SWCIS-2026-0358` under SWCIS `5.4.0`. It reconciles the current
checkout without activating it in any runtime, restarting a service, contacting
a provider, or changing an engineering rule.

## Verified current state

`python tools/rulebook_closure_diagnostics.py` validates all seven registered
Mechanical modules against the canonical Draft 2020-12 rule schema, checks
source-entry counts, duplicate identities, forbidden automatic PASS behavior,
known rule mappings, and reciprocal executable-source links.

The current checkout result is bounded-integrity `PASS`:

| Module | Version | Rules | Registered source entries | Coverage claim |
|---|---:|---:|---:|---|
| rainwater | 2.85.1 | 103 | 534 | bounded registry only |
| water | 1.2.0 | 12 | 13 | bounded batch |
| sanitary/vent | 1.2.0 | 10 | 10 | bounded batch |
| heating | 1.1.0 | 5 | 5 | bounded batch |
| cooling | 1.0.0 | 2 | 2 | bounded batch |
| ventilation | 1.0.0 | 2 | 2 | bounded batch |
| gas | 1.2.0 | 6 | 6 | bounded batch |

For rainwater, all 103 registered rules are strict-schema valid, all 534
registered entries have a disposition, and the registry currently contains
zero `UNRESOLVED_CONTROL` dispositions. This closes the earlier 58-rule/139-
schema-error defect in the registered checkout data. It does **not** prove that
the source inventory itself covers every page, clause, figure, table, symbol,
map, exception, or later amendment in M4, M6, M14, M16, or M17.

## Items that cannot truthfully be closed from current evidence

The following remain explicit evidence blockers, not software PASS results:

1. Complete statutory coverage is false or undeclared for every registered
   module. The six non-rainwater modules are intentionally small source batches.
2. The rainwater handoff has 534 extracted entries, but there is no sealed,
   independently verified page-by-page inventory proving coverage of the stated
   543 original pages plus every figure, table, symbol, and amendment.
3. Snow-map assignment, all wind-figure coefficients/geometric domains, and all
   M16 symbols require source-qualified visual/digitization evidence where the
   current contracts depend on external figure evidence. No missing coefficient
   or location is inferred.
4. The printed Appendix 7 horizontal `DN250 @ 4%` value remains preserved as a
   print anomaly (`15984 m²`, `112.52 L/s`). It is not silently corrected and
   requires official interpretation before it can support an approval claim.
5. Checkout rainwater 2.85.1 is not the deployed runtime Rulebook. Runtime
   activation, migration, restart, staging, production publication, and
   professional engineering approval were not authorized in this work.
6. No private source drawing, generated customer DXF, permit, physical test,
   manufacturer certificate, municipal approval, or structural approval was
   created or treated as software evidence.

## Completed implementation package: water network sizing

The canonical hydraulic sizing module now exposes
`design_water_network_from_rulebook`. It derives cold/hot SFU from the typed
fixture class and count, selects only an exact verified M16 Appendix 1 probable-
demand row, and carries the source Rule IDs and module version into the result.
It also prevents hydraulic selection below the applicable M16 fixture-branch
minimum DN.

For galvanized-steel segments, the same entrypoint now derives fitting
equivalent length from the exact selected DN and typed fitting/count inventory
using M16 table P1-4-5-3. It updates effective route length and friction head,
records the governing Rule ID, rejects a conflicting declared length, and
returns `INPUT_REQUIRED` for an unsupported DN or fitting. The table is not
borrowed for copper, plastic, or another material.

The remote-outlet pressure evaluator now binds the sized path to the exact M16
fixture pressure row. It consumes explicit source static and flowing pressure,
source/outlet elevation, calculated segment friction, and explicit meter/valve
losses. It independently checks the 4 bar maximum static pressure and the
fixture-specific minimum flowing pressure, emitting a stable calculation ID and
Rule ID. Missing source pressure, geometry, local loss or sized-path evidence is
`INPUT_REQUIRED`; no generic 15 m residual-pressure assumption is used.

## Completed implementation package: sanitary main sizing

The canonical sizing module now derives accumulated sanitary load from exact
M16 Appendix 3 fixture DFU rows and selects the smallest main-horizontal DN
whose exact DN/slope row supports that load. The result carries stable
calculation identity, source Rule IDs and drawing DN reconciliation. A slope
not printed in the registered table, an unsupported fixture, incomplete
downstream inventory or missing path remains `INPUT_REQUIRED`; over-capacity or
drawing/calculation DN mismatch is `FAIL`. No interpolation between slopes or
pipe diameters is performed.

Branch and stack sizing now use the exact M16 segment-kind capacity columns and
select the smallest supported DN after accumulating typed fixture DFU. Vent-
stack sizing retains the original inch/foot source units and selects the
smallest printed vent diameter whose exact waste-diameter@DFU row covers the
developed length. Unknown DFU combinations remain `INPUT_REQUIRED`; table
overlength is `FAIL`.

The cleanout consumer validates a complete network inventory against the five
required location classes, pipe-sized openings through DN100, minimum 450 mm
working clearance and maximum 30 m main-horizontal interval. It emits a stable
calculation identity; missing numeric evidence is `INPUT_REQUIRED`, while an
incomplete inventory or geometric violation is `FAIL`.

Vent route sizing now enforces at least half the waste DN, never below DN32,
and one nominal size increase strictly beyond 12 m. Trap-to-vent distance is
measured from the supplied polyline geometry and checked only against the exact
DN@2-percent rows. Termination clearance is derived from 3D terminal/opening
points, with the printed 3 m horizontal or 1 m-above alternative; wall exits
add property, ground-height and canopy checks.

An isolated synthetic DXF regression materializes the same calculation-bound
vent route into dedicated plan, riser and schedule layers, saves the issued
file, independently reopens it, and verifies geometry plus calculation/DN label
identity. This proves the additive materializer, not activation in the customer
runtime or completeness of a real project package.

## Completed implementation package: heating installation

The M14 heating consumer now produces calculation-bound schedules for exposed
surface guards, floor-mounted equipment bases and open/closed expansion tanks.
Tank capacity remains an explicit project/engineer selection tied to system
water volume, operating-temperature range and maximum working pressure; no
capacity formula absent from the reviewed source is invented. Open tanks enforce
the exact 1200 mm water-level clearance, while closed tanks require an accredited
test report at not less than 1.5 times working pressure. The output is explicitly
non-release-authoritative until all project evidence is present.

## Completed implementation package: bounded residential and parking ventilation

The exact M14 rates now drive calculation-bound exhaust duties of 50 L/s
(180 m3/h) per residential kitchen and 25 L/s (90 m3/h) per residential
bathroom/toilet. Round-duct selection consumes an explicit velocity limit and
candidate-diameter set; neither is presented as a statutory default. Intake
separation is derived from 3D intake/exhaust points and enforces 3 m horizontal
or 1 m below hazardous/contaminated exhaust. The source exception for ordinary
residential kitchen/bath exhaust is preserved. At that stage, parking and other
usage rates remained `INPUT_REQUIRED`; the source-verified parking extension is
recorded below, while still-unknown usages continue to fail closed.

The official M14 second-edition (1391) PDF was independently fetched from the
INBR source and matched the registered SHA-256
`5a6ec8e94cc08c2a1349d1ef67bb6fcff6a4c9ac594052cce41701cbacfe569e`.
Visual and text review of printed pages 41-42 added only the unambiguous parking
rows and control clause: private parking uses 50 L/s per automobile, common
parking uses 7.5 L/s per square metre, and enclosed parking/garage systems must
have full capacity of 7.5 L/s per square metre while automatic pollutant control
may not reduce capacity below 0.25 L/s per square metre. The CO control setpoint
must remain strictly below 25 ppm. Vehicle count, floor area, enclosure, control
sequence and setpoint remain explicit evidence; missing evidence is
`INPUT_REQUIRED`. The full duty is passed to the explicit-basis round-duct
selector. No legacy `parking=250 CFM` constant is accepted as code evidence.

Visual review of printed pages 42-43 then added 27 unambiguous single-basis
outside-air rows for residential rooms, offices, hotels, assembly, retail,
laundry, sports, educational and public spaces. Each row preserves its printed
per-person or per-area basis and its paired rounded imperial value. The engine
uses only the printed SI rate with a verified occupant count or floor area and
passes the resulting duty to the explicit-basis duct selector. Dormitory and
other rows with simultaneous per-person and per-room values remain
`INPUT_REQUIRED` until the source-defined combination method is independently
established; no sum, maximum or alternative interpretation is guessed.
Review of the table heading, adjacent clauses and visible notes found no rule
for combining simultaneous per-person and per-room entries. Those rows remain
an explicit source-semantics blocker rather than receiving a locally invented
sum, maximum or alternative interpretation.

The official M17 fifth-edition (1403) PDF was independently fetched from the
recorded INBR URL and matched SHA-256
`eb575703d82dfe524ea227c1115c487f0d8c65aebb96442859ff68795fa70cc8`.
Printed page 84 visually confirms table 17-4-10, its `m3/h` units, welded-steel
scope, 176 mm water-column inlet pressure, 12.7 mm water-column maximum drop and
relative gas density 0.65. The existing canonical project-draft gas consumer
now transcribes all 30 length rows and all nine printed diameter columns from
DN15 through DN100, feeds the resulting 270 cells into
`design_gas_network`, carries table/page/hash/condition metadata and blocks
service pressure below the table condition. This verification does not extend
the table to another pressure, pipe material, diameter or unprinted length.

Printed page 85 Table 17-4-11 adds exact natural-gas relative-density
correction factors for densities 0.50 through 1.00. The canonical table loader
now applies an exact factor before gas sizing and rejects an unprinted density
instead of interpolating. This extends density handling only; it does not make
Table 17-4-10 applicable to another inlet pressure, pressure drop or material.

## Local activation plan — not executed

1. Freeze and review the exact Git revision; do not activate a dirty checkout.
2. Read the durable queue and worker state and proceed only with zero active
   analysis, design, finalization or deliverable jobs and no user test underway.
3. Build a derivative local image from the canonical unversioned entrypoint;
   preserve PostgreSQL, volumes, customer sources and prior artifacts.
4. Run the 311-test isolated suite, SWCIS, build-identity and runtime-version
   guards before replacing any container.
5. Activate only during a declared local maintenance window, then verify health,
   module dependency identities and one synthetic no-provider journey.
6. Roll back by restoring the prior approved image/Git revision; never copy a
   historical Python runtime module or mutate project data.

This plan does not authorize a restart, deployment, provider request, real
project regeneration or database migration.

## Runtime connection and concurrent-work status

- `app/mechanical_rulebook.py` imports `ventilation_design_profile`. The
  independent ventilation-package checkout path now calls
  `design_ventilation_from_rulebook` when the versioned design overlay contains
  typed `ventilation_spaces` plus explicit duct criteria. Incomplete typed
  space evidence returns `INPUT_REQUIRED`; old contracts without the additive
  field keep their legacy explicit-CFM path for compatibility.
- The M17 table loader is called by the independent gas-package graph and feeds
  `design_gas_network`. Use of the official table now requires explicit
  `gas_relative_density` in the design overlay; missing or unprinted density is
  `INPUT_REQUIRED`. Density, Table 17-4-11 factor and source identity are
  carried into each calculation row.
- Conditional project fields now carry exact-row gas density plus explicit duct
  velocity and candidate diameters from the questionnaire through normalized
  answer persistence into the draft engineering overlay. Typed ventilation
  spaces are derived only from source-bound residential kitchen, bathroom and
  toilet room classifications; other occupancies remain evidence-bound.
- `standards/active-release.json` and `cad_engine/build_identity.py` still name
  `mechanical-rulebook/5.2`. Checkout module versions and SWCIS revisions do not
  change that active release identity.
- This checkout also contains unfinished upload-diagnostics and administrator
  work owned by other Works. Activation must start from a reviewed, isolated
  Git revision containing the intended closure only; it must not package the
  shared dirty worktree or overwrite either concurrent workstream.

Activation order remains: reconcile/merge the isolated Rulebook change through
approved Git history; wait for the other Works to reach a safe handoff; confirm
zero active jobs and no user test; build a derivative local image; run the 311
tests, SWCIS, runtime-contract/build-identity guards and one synthetic no-provider
journey; then activate only in a declared maintenance window. No such activation
was performed here.

## Remaining evidence-bound work by discipline

- Water: graphical pipe-sizing curves and unreviewed copper/plastic equivalent-
  length tables require governed digitization from the original source.
- Sanitary/vent: combinations absent from the exact registered tables cannot be
  interpolated; real-project routing and customer-runtime activation remain
  separate work.
- Heating: expansion-tank capacity calculation and full pipe sizing require an
  authoritative formula/table and explicit project temperatures/pressures.
- Cooling: equipment capacity and service-clearance acceptance requires exact
  official manufacturer data for the selected product; the current module is a
  bounded placement/control contract only.
- Ventilation: parking and the 27 verified single-basis outside-air rows are
  executable. Multi-basis rows and exhaust-note rows outside the already
  registered residential/parking scope remain open until their combination or
  fixture/room basis is independently established.
- Gas: table 17-4-10 is independently hash/page verified and already consumed
  for its exact low-pressure welded-steel conditions. Other M17 sizing tables
  across pressure, material and diameter remain outside the registered six-rule
  gas module and cannot be inferred from table 17-4-10.
- All disciplines: runtime activation, a real project contract, professional
  review, permits, physical tests and issued-artifact approval remain external
  gates. The local activation plan above is prepared but not authorized.

This closes the executable connection from the existing water Rulebook tables
to the real segment hydraulic calculator. It deliberately leaves candidate
diameters, Hazen-Williams coefficient, velocity limit and pressure-drop limit as
explicit project/internal hydraulic-basis inputs. A non-tabulated SFU total,
unknown fixture class, unsupported mode or missing hydraulic criterion returns
`INPUT_REQUIRED`; the unreviewed graphical sizing curves are not interpolated or
digitized.

## Reproducible checks

Run the offline audit and focused regressions with the repository's isolated
Python 3.12 environment:

```text
.venv-panel-test/bin/python tools/rulebook_closure_diagnostics.py
.venv-panel-test/bin/python -m pytest -q tests/test_rulebook_closure_audit.py
.venv-panel-test/bin/python -m pytest -q tests/test_water_rulebook_sizing_integration.py tests/test_sizing_v14.py tests/test_water_executable_rulebook.py
.venv-panel-test/bin/python -m pytest -q tests/test_rainwater_executable_rulebook.py tests/test_water_executable_rulebook.py tests/test_sanitary_vent_executable_rulebook.py tests/test_heating_executable_rulebook.py tests/test_cooling_executable_rulebook.py tests/test_ventilation_executable_rulebook.py tests/test_gas_executable_rulebook.py
```

An audit `PASS` means registered-data integrity only. It cannot be used as a
statutory-completeness, runtime-activation, permit, construction, or engineer-
approval claim.
