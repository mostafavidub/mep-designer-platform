# Local Jurisdiction and Project Code Basis

This offline R&D capability records municipal sources without claiming that any real
municipal requirement has been collected or professionally approved.

`LocalRuleProfile` owns jurisdiction, effective dates, official-document identities,
clause mappings and local-rule interpretation status. `ProjectCodeBasis` owns the exact
project/parcel binding, current Site Model, Owner Program reference, national/local
profiles, applicability, conflicts and derived constraints.

The only V1 source-acquisition path is hybrid intake. Candidate facts may be extracted
from an official file, but structural completeness is distinct from source authenticity,
regulatory applicability, reviewer qualification, professional approval and runtime
authorization. Embedded review fields and caller-created source snapshots cannot prove
authority. This PR defines an `AuthorityEvidenceResolver` interface for a future
independently governed provider, but supplies no trusted provider or qualification
entrypoint. Consequently, real-like records remain `AUTHORITY_REVIEW_REQUIRED`, and
`AUTHORITY_QUALIFIED` is unreachable through self-asserted payload fields.

The three disclaimer markers are optional fixture annotations in the public schemas.
Repository synthetic fixtures must contain exactly `NON_GOLDEN`,
`NON_REGULATORY_TEST_DATA` and `NOT_PROFESSIONALLY_APPROVED`; marked records are capped
at `STRUCTURALLY_VALID`. Absence of markers is not authority evidence.

The envelope calculator is deliberately bounded to convex polygons in metres with an
explicit CRS and one source-backed setback per edge. It never repairs surveys or infers
setbacks. Complex parcels return `AUTHORITY_REVIEW_REQUIRED`; missing local rules return
`LOCAL_RULE_REQUIRED`; stale identities return `STALE_BINDING`; unresolved national/local
conflicts return `CONFLICT_REVIEW_REQUIRED`. Coordinates, setback values and dependency
fingerprints are validated before clipping; non-finite values, zero-length edges and
malformed constraints return structured `INPUT_REQUIRED` findings without repair.

Project validation re-resolves the current Site Model, Owner Program, full
`LocalRuleProfile` and national binding. It compares project/parcel identity, revisions,
hashes, country, province, city, municipality and material district/zone values, and
evaluates profile and rule effective intervals at the project date. Applicability source
references must resolve to current rule/source identities. Result precedence is:
`INPUT_REQUIRED`, `LOCAL_RULE_REQUIRED`, `STALE_BINDING`,
`CONFLICT_REVIEW_REQUIRED`, `AUTHORITY_REVIEW_REQUIRED`, then
`STRUCTURALLY_VALID`. A higher-priority missing or malformed input is never hidden by a
lower-priority conflict or review state.

Real-project qualification requires the parcel/cadastral identity, current survey,
municipal instruction map, planning zone, effective permit/design date, setbacks,
building line, coverage/FAR/height, parking/access requirements, and every applicable
parcel exception or local fire/accessibility/elevator directive.

No runtime imports, Generator integration, Golden execution, database migration or
customer-data rewrite are part of this capability.
