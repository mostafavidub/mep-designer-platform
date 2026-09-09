# Roof rainwater and graph-derived riser contract

Status: governed by MEP-ROUTE-001, MEP-SIZE-001 and MEP-SUBMIT-001.

## Roof rainwater

An issue-ready rainwater design requires a supplied roof boundary, catchment
polygons, low points, drains, emergency overflows, stacks, slopes, project
rainfall intensity, runoff coefficient and governed drain/downpipe capacity
tables. Flow is calculated independently for every catchment as
`area × rainfall intensity × runoff coefficient / 3600` in L/s.

Each catchment must connect its low-point drain to a known stack and retain one
Calc ID across calculation, plan segment, riser and schedule. Missing catchment
geometry or rainfall is `INPUT_REQUIRED`; inadequate slope, invalid low point,
unknown stack or unavailable capacity is `FAIL`. A generic roof coordination
schematic cannot satisfy the roof-rainwater gate.

## Riser

Risers are deterministic projections of the plan network graph. Their source
graph hash changes whenever plan nodes, edges, execution data or typed levels
change. Every segment enforces `Plan ID = Riser ID = Calc ID = Schedule ID`.

Allowed riser level types are `GROUND`, `FIRST`, `SECOND`, `ROOF`, `BASEMENT`
and `MEZZANINE`. Detail sheets and identifiers beginning with `DETAIL` are
forbidden from the riser level set. Dangling graph edges, missing execution data,
invalid levels or identity mismatches block issue.
