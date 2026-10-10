# Local Jurisdiction and Project Code Basis

This offline R&D capability records municipal sources without claiming that any real
municipal requirement has been collected or professionally approved.

`LocalRuleProfile` owns jurisdiction, effective dates, official-document identities,
clause mappings and local-rule interpretation status. `ProjectCodeBasis` owns the exact
project/parcel binding, current Site Model, Owner Program reference, national/local
profiles, applicability, conflicts and derived constraints.

The only V1 source-acquisition path is hybrid intake. Candidate facts may be extracted
from an official file, but a qualified source or rule requires an independently supplied
current registry record and a scope-bound review. Synthetic fixtures are capped at
`STRUCTURALLY_VALID` even when they exercise the complete contract.

The envelope calculator is deliberately bounded to convex polygons in metres with an
explicit CRS and one source-backed setback per edge. It never repairs surveys or infers
setbacks. Complex parcels return `AUTHORITY_REVIEW_REQUIRED`; missing local rules return
`LOCAL_RULE_REQUIRED`; stale identities return `STALE_BINDING`; unresolved national/local
conflicts return `CONFLICT_REVIEW_REQUIRED`.

Real-project qualification requires the parcel/cadastral identity, current survey,
municipal instruction map, planning zone, effective permit/design date, setbacks,
building line, coverage/FAR/height, parking/access requirements, and every applicable
parcel exception or local fire/accessibility/elevator directive.

No runtime imports, Generator integration, Golden execution, database migration or
customer-data rewrite are part of this capability.
