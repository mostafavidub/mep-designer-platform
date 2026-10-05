# Commercial Measurement Authority — shadow foundation

Readiness: `COMMERCIAL_MEASUREMENT_PARTIAL`. This implements deterministic internal
measurement, bounded review, financial safeguards and read-only pricing. It does
not establish real-project gross-area accuracy or activate customer pricing.

## Audit and root cause

Starting branch `feature/architecture-stack-integration`, commit
`062dd76951a51dd141934018a11eac29db814778`, clean new worktree. Main remains
`9876f3fb0cb63e17055ff2d30e621fa2c9325939`; integration is PR312. Railway read-only
inspection on 2026-10-05 found Staging's successful web deployment
`b783db75-4129-4999-adeb-f1e15284d873` at the same integration SHA. Its other
application service reports main9876f3f; do not claim all Staging services share
the architecture commit. No configuration, deployment, production DB or pricing
settings were changed or read from a private production database.

Symptom: `app/commercial_flow.py:project_area_m2` accepts
`architectural_auto.geometry_area_m2`, then analysis/file values, with numeric
range checks. `app/unit_sanity.py` still computes width × height of global
`geometry_bounds` whenever a plausible-single-plan size/aspect heuristic passes.
`app/main_auto.py` also exposes geometry dimensions. Runtime regression verifies
that a 250m² value drives the existing configured-rate quote; a targeted probe
verifies plausible whole-file extents become area even without Level authority.

Root cause: geometric extent, commercial gross footprint, source scope and
financial authority share one unqualified scalar. Width/height plausibility does
not prove that a rectangle is a building floor. Several floor plans, title blocks,
sections or remote objects can inflate it; missing levels or Typical multiplicity
can underbill. Summing successfully recognized rooms would introduce a different
underbilling defect. The repair direction is a separate evidence-bound contract,
not another fallback in `project_area_m2`. **The known legacy weakness remains in
the live path by explicit shadow-only scope.**

ProjectQuote is unique per project and stores amount/paid/time, not source/model
or pricing identity. `quote_for` creates once; later calls display current area
and rates alongside the old amount. Re-upload/re-analysis can replace project
analysis without financial source binding. Payment guards read that same paid
row; wallet/gateway paths mutate it. `service_pricing` seeds defaults on read if a
row is missing. Shadow therefore never invokes either write-on-read helper.

The current application also registers `panel_bridge` / `panel_checkout`. Its
separate `panel_checkouts` order accepts a bounded, finite browser-confirmed area,
uses server ServicePricing, and binds a quote token to amount/answers/area. It
already preserves paid orders and atomically coordinates wallet/ledger/job writes;
that token still does not bind source/model/build/pricing-version identity. Thus
it is inaccurate to describe every current payment surface as the legacy
ProjectQuote lifecycle. Shadow accepts the server's panel_checkout model namespace,
reads an existing order if present and labels/selects it as the comparison source;
otherwise the comparison explicitly identifies the legacy ProjectQuote. Both
financial models, their tokens, ledger and live paths remain unchanged. The SQL
integration test verifies both paid models and the correct panel comparison.

Authoritative architecture remains `reconstruct_architecture` → current
`architecture_contract.adapt_current_architecture` (3.0) → independent validator
and Preflight. Per-file producer evidence lives in
`analysis.files[].canonical_architecture_model`; Preflight uses a separately
persisted canonical model/review registry. Envelopes still live in the bound
legacy producer model, not as an independently qualified gross-area collection
in canonical3.0. The projection requires both matching objects and their source
identities; no stale snapshot or unbound legacy dictionary supplies authority.

Current envelopes can be wall-axis cycles or interior-region unions. Their
HIGH_CONFIDENCE label does not establish outer-face gross area. Region union and
room accounting share upstream geometry and are explicitly correlated checks.
Current unit calibration can vote from frame size and dimension magnitude;
INFERRED is not a trusted commercial scale. Declared/header conflict is CONFLICT.
Explicit represented levels/title handles are reused; geometry similarity never
supplies multiplicity. Existing semantic pilot truth is not a commercial Golden.

## Contracts and authority

- `planha-commercial-measurement/1.0`, measurement1.0.0, rule `commercial-gross/1.0`.
- `planha-commercial-shadow-quote/1.0` with ServicePricing row id, update time and
  content fingerprint, service, rates, minimum, final integer amount and timestamp.
- `planha-commercial-golden/1.0` stores independent human inventory and area truth.

Input is an internal, server-resolved list of canonical/producer pairs plus the
current complete upload SHA set and project identity. A client must never choose
those bindings. The offline manifest is an operator tool, not an HTTP authority
endpoint. Model hash, producer semantic hash and additional scale/region/dimension
evidence hash are verified. Build identity comes from the canonical build module.

Only existing envelope components are measured. No bounding box, offset, room
union or new polygon is constructed as the commercial boundary. Each boundary
must coincide exactly with existing canonical wall faces and independently valid
source separator witnesses. Centerlines, unsupported/vision wall grants, invalid
rings and unknown hole scope block. Holes are not silently subtracted from gross;
current hole/courtyard cases require additional architectural scope qualification.
Disconnected components are all inventoried; incomplete proof for any component
blocks the entire amount. Partial subtotals are not released as a project price.

Source-title classification or bounded interpretation distinguishes every locked
class. Only ROOF and YARD/SITE are commercially excluded. SECTION, ELEVATION,
DETAIL and REFERENCE_ONLY are non-Level drawings. Unknown and mixed roof/yard
views fail closed. Enclosed roof-headroom interpretation is not automatically
excluded as an ordinary roof. Basement, parking, ground, ordinary floor, mezzanine,
balcony, terrace and other building floors are included when independently qualified.
Separate balcony presentations sharing a Level cannot simply be added: they remain
blocked as duplicate/scope ambiguity until a future source-qualified component
accounting extension. No additional commercial exclusion is introduced.

A project-wide completeness question prevents an incomplete detected inventory
from being mistaken for a complete project. Building membership uses confirmed
existing frame representatives, including multiple buildings and multiple DXFs.
Unknown grouping blocks. Same building/physical-Level identity in two views,
including overlapping Typical ranges, blocks the project. Similar polygons on
distinct, explicitly named levels are not deduplicated. Typical multiplication
requires an explicit title range matching the represented Level set; guessed
counts and empty inventories block. Missing ranges currently request better
source input, rather than offering an invented floor-count choice.

Scale uses explicit supported INSUNITS and matching declared/effective calibration;
heuristic inference and inconsistent/missing scales fail closed. Area is Decimal
shoelace area × metres_per_unit². Geometry topology uses existing Shapely. Native
DIMENSION entities on adjacent overall rectangular edges provide a separate
source-entity comparison, with handles, primary/comparison values and deltas.
This is not an independent units certificate: scale is gated separately. No
source dimension, or unsupported/nonrectangular overall geometry, remains input
required. Exact arithmetic equality is a conservative synthetic-only acceptance
condition, **not a real-project error tolerance**. No engineering tolerance was
selected without Golden evidence. Room net-area differences are diagnostic; a
physical-space sum exceeding gross is a conflict, while unrecognized rooms do not
erase gross. Further independent methods/real numerical tolerances remain unqualified.

## Review, stale data and persistence

Questions bind project, complete sources, model and evidence identities, build,
rules, object and allowed answers. Replay rejects unknown fields, numeric geometry
injections, changed bindings and conflicting duplicate answers; identical replay
is idempotent. Interpretation does not rewrite the architecture model. Every run
rechecks source/model integrity, independent architecture validation, perimeter
support, dimensions and accounting. Human gross-scope confirmation alone cannot
promote centerlines or missing wall proof. No public review API or customer UI is
introduced. Operator identity and audit timestamp must be supplied by the trusted
internal caller; hashes are integrity bindings, not authentication signatures.

Persist via immutable private content-addressed JSON sidecars. Store artifacts
and their source/model manifests on durable access-controlled project storage in
any future deployed worker; local disk is only offline qualification storage.
Current Project.analysis, uploads, source files, revisions and customer tables
are unchanged. Current source list is mandatory at replay. The internal service hashes the current project architecture.dxf or DXF members of architecture.zip (no CAD parse), checks the project-directory identity and persisted per-file model hashes, and rejects stale Project.analysis before reading pricing. Source/model/build/
rules/review change invalidates prior measurement. Pricing-row identity/rule
change invalidates the shadow quote. Paid rows are never rewritten; a future paid
scope revision needs a separately authorized adjustment ledger. No destructive
or additive production DB migration occurs in this change.

`run_internal_shadow(project, db, app.state.commercial, ...)` issues SELECTs with
no autoflush, reads actual ServicePricing and any existing ProjectQuote, then
projects and compares. Missing pricing blocks rather than creating defaults.
No process startup hook, queue activation, route, live quote replacement, wallet
mutation or provider call is installed. The integer monetary formula retains the
existing nearest-integer/half-even policy explicitly with Decimal arithmetic:
`max(minimum_price, rounded(area * rate))`. All source/rate values remain separate.

## Golden and qualification workflow

Run `python tools/commercial_measurement.py --manifest <private.json> --output
<private-directory>`. Manifest: `projects[{project_id,sources[{source_sha256,
canonical:<path>,legacy:<path>}]}]`. Uses existing models; never reparses DXF.
The output includes immutable measurements, benchmark, Persian HTML and empty
human Golden request forms. Observed frame inventory is labeled NOT TRUTH.
Start with one independently reviewed complete project; request building count,
complete Level inventory, classes, gross area with method/provenance, Typical
multiplicity and total. Never copy Planha areas into Golden truth. Source files,
images, coordinates, review maps and customer artifacts remain outside Git.

Benchmark reports building count, billable count, class, multiplicity and area
errors separately from operational state rates. Unmeasured metrics are null,
never zero. No real Golden gross-area truth exists in the available architecture
pilot. All seven current models fail commercial qualification; no real shadow
price is proposed. This is **PARTIAL**, not merely awaiting a signature: current
architecture does not yet export sufficient qualified gross/scale/check evidence.

## Impact and rollback

Architecture reconstruction/canonical/Preflight: read-only inputs, no engine fix.
Project.analysis/re-upload/revisions: no writes; current source manifest required.
Commercial flow/ProjectQuote/ServicePricing/payment/wallet: existing implementations
unchanged; SELECT-only isolated service. Database/API/UI: no migration, route or
customer display. Mechanical/future Electrical: service-specific rate separation,
no change to engineering scope, calculations, PMM or generation. Storage/privacy:
private sidecars and references; no DXFs or credentials committed. Performance:
reuse existing output, no parse/provider call; independent validation is required
and not elided for speed. SWCIS5.2.0 / CR0300 / COM-AREA-001 / ADR and migration
contract apply; no gate weakened.

Rollback is reverting the approved change commit and ignoring the new sidecar
schemas. Live price/paid records require no rollback because they were not touched.
Merge, Staging and Production need separate owner authorization. Staging is not
the next cheapest test: resolve gross-envelope/scale qualification and obtain
independent Golden evidence first. No owner browser test is requested for checks
already covered by automated integration tests.

## 10-step governance impact

1. added — COM-AREA-001, existing engineering Rule Book untouched.
2. verified — PMM untouched; independent commercial contract.
3. added — bounded project/source/build-bound commercial interpretation.
4. not affected — engineering planner.
5. verified — existing CAD geometry consumed without edits.
6. not affected — routing, sizing and equipment.
7. not affected — details, risers and engineering drawing output.
8. added — financial destructive, replay, schema, SQL-read-only and Golden tests.
9. added — immutable shadow manifest and stale-binding checks.
10. changed — SWCIS5.2.0, CR0300, capability/changelog/graph/migration; no deployment.

## Local validation evidence

Python3.12.13, isolated SQLite/DATA_DIR/CAD_OUTPUT_DIR, provider disabled.
Full governed regression: **1480 passed + 14 subtests**, no skipped tests.
Commercial/Golden plus governance contract subset: **92 passed**. The three new
commercial test files contain **76 cases** (parameterized cases counted).
`git diff --check`, Python AST parsing, runtime-version guard and SWCIS pass.
CI adds pinned jsonschema4.26.0 to both existing full-suite runners (Web and Mechanical Coordination) and expands
Web Regression to all PR base branches, including this stacked PR. Existing main
coverage and all tests remain mandatory; no check is weakened. Other workflows
retain their existing triggers; NOT_TRIGGERED is not reported as PASS. Official
CI is reported on the PR.

The first full collection failed because CAD_OUTPUT_DIR defaulted to unwritable
/data; rerun used isolated temporary storage. An intermediate SWCIS inventory
failure was fixed by registering components under the existing governed ui_api
module, retaining the locked module-inventory validator unchanged. Neither failure
was skipped or waived. The final full run passes all existing and new cases.

A–AJ coverage is explicit in `tests/test_commercial_measurement.py`: single/multiple
floor; all seven named billable types; three commercial exclusions; section,
elevation/detail/titleblock; explicit and unproven Typical counts; duplicate and
overlapping ranges; two buildings; multiple plans/source; one source/Level; rotated
m/mm; inferred/ambiguous/conflicting scale; dimensions including compensating errors;
disconnected regions; balcony/yard ambiguity; distant titleblock/detail/extents;
room absence and excessive physical sum; re-upload; deterministic source-order and
review replay; and unsupported geometry. SQL integration adds actual paid/live/
wallet immutability and current-upload-versus-analysis stale detection. Golden tests
reject absent, algorithm-generated and stale truth and expose wrong-area authority.

Two existing sealed Architecture runs per source were projected without reparse:
7/7 deterministic, 7/7 CONFLICT, zero real shadow amounts emitted, zero provider
calls. Current scale conflicts and unqualified gross boundaries remain explicit.
Observed projection/validation latency was approximately0.5–1.7s/source on the
local machine (not a deployed SLA). All28 consumed Architecture files remained
byte-identical. All56 original blind payload hashes also matched their14 seals.
There is no independently verified commercial Golden denominator: accuracy and
false-authority metrics remain unmeasured, rather than reported as zero errors.

The initial Mechanical Coordination remote run failed only because its separate
full-suite environment lacked jsonschema. The dependency was added there as well;
no test or check was skipped to resolve it. Final CI evidence supersedes that run.
