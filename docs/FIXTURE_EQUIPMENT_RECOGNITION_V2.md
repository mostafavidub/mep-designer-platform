# Deterministic fixture and equipment recognition v2

The canonical runtime is `cad_engine.fixture_recognition.recognize_fixtures_equipment`.
It consumes the single canonical architecture extraction; it does not parse the
DXF itself. `mep-object-candidate/2.0` records deterministic ID, representation,
world anchor/bounds, source handles, root insert, nested path, transform,
definition, geometry signature, evidence families and four independent axes:

- recognition: `UNCLASSIFIED`, `OBJECT_CANDIDATE`,
  `DETERMINISTICALLY_CONFIRMED`, `AMBIGUOUS`, `REJECTED_NON_MEP`;
- plan context: `MAIN_PLAN`, `DETAIL_OR_LEGEND`, `OUTSIDE_PLAN`,
  `AMBIGUOUS_CONTEXT`;
- hosting: `HOSTED_PHYSICAL_SPACE`, `HOSTED_CANDIDATE_SPACE`,
  `SEMANTIC_ZONE_ASSOCIATED`, `UNHOSTED`;
- authority: `PREANALYSIS_EVIDENCE`, `INPUT_REQUIRED`,
  `ENGINEERING_ELIGIBLE`.

Exact block identity, exact object attributes, object-specific layers with
source geometry, nested provenance, and same-file exact geometry-family
propagation are deterministic evidence. Room labels and semantic zones are not.
Unknown geometry remains ambiguous. Detail/legend evidence is rejected from the
installed-object path. Type ports are requirements metadata and never create
connection coordinates.

The legacy `detections` projection is intentionally narrower than
`confirmed_objects`: only confirmed, main-plan, physically hosted objects enter
it. Existing system-requirement and network consumers therefore remain fail
closed, while unhosted confirmed objects remain visible for investigation.

Private source audits and overlays are generated with
`tools/run_fixture_recognition_audit.py` and remain outside Git. The committed
suite covers named, anonymous, nested, rotated/scaled/mirrored, exploded-layer,
unhosted, detail/legend, room-label destructive, signature propagation,
deduplication, deterministic-ID and zero-authority cases.
