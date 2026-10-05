# ADR: Separate commercial gross measurement from live pricing

Status: accepted for shadow implementation; real qualification PARTIAL.

The legacy scalar geometry_area_m2 can be a whole-file extent. Replacing it with
another heuristic would preserve false financial authority and mutate live behavior.
Use one read-only projection of bound existing Architecture evidence instead.
Keep versioned measurement and rate-based shadow quote separate. Fail closed on
unknown gross perimeter, unit/Level/building scope, duplication and reconciliation.
Bounded human interpretation cannot construct geometry. Internal source resolution
and access control remain the caller's responsibility; no public route is added.

Consequences: conservative low coverage, especially current wall-axis envelopes,
heuristic unit calibration, missing independent gross dimensions and separately
presented balconies. This is preferable to an apparently plausible automatic price.
Independent real human Golden facts and evidence-derived numerical thresholds are
mandatory before financial release. Synthetic tests prove safety controls, not
market accuracy. Sidecars avoid customer-table migration; paid records stay
immutable and future changes require separate adjustments. No live activation.
