# Mechanical Network Authority v19

## Purpose

This contract governs steps 4–6 of the mechanical design chain: topology extraction/generation, segment execution sizing/material annotation, and CAD materialization. It is intentionally fail-closed and does not convert recurrence in the owner-supplied reference corpus into a design rule.

The authoritative chain is:

`PMM v3 level evidence -> installed DXF fixture/equipment evidence -> logical network graph -> explicit segment calculation/basis -> size/material/slope -> graph-native CAD entity -> exact-file reopen QA`

## Step 4 — topology authority

`cad_engine/topology_authority_v19.py` may assign an installed fixture/equipment to a level only from an explicit assignment, an unambiguous PMM level `region_bounds`, or the sole level in a one-level PMM. Multi-level ambiguity is `INPUT_REQUIRED`.

Only real architectural shaft geometry may become a shaft node. A provisional floor-center shaft is forbidden. `DETAIL-*` and other non-architectural pseudo-levels are not valid riser levels. Coincident logical nodes never create a synthetic service loop merely to make a visible line.

Endpoints aggregate into branches and then into a real source, wet core, or shaft. Duplicate logical edges are a hard failure. Pre-coordination plan paths are orthogonal and may cross walls, but they may not cross a detected structural obstacle; an unresolved obstacle requires route coordination rather than a fabricated detour. Full issue coordination remains subject to the structural/RCP v19 gate.

Every edge receives one stable calculation identity, and the same identity is used for Plan ID, Riser ID, Calculation ID and Schedule ID.

## Step 5 — segment execution authority

`cad_engine/sizing_authority_v19.py` never supplies fixture loads, numeric size tables, material choices, slope percentages or route offsets. A segment is executable only when these values are supplied by an explicit segment design row, an already-authoritative supplied graph, or an explicit project/system design basis.

When a system design basis performs table selection, it must provide endpoint loads, load unit and a complete size table. Materials require both a value and source. Gravity systems require an explicit slope percentage. No value observed in Project 10 or any other reference project is a hidden generation default.

Exact duplicate geometry within one system fails. Exact overlap of paired systems such as cold/hot water or sanitary/vent returns `INPUT_REQUIRED` until an explicit plan separation offset is supplied. Direction changes are recorded as route-geometry evidence and are not silently promoted to a manufacturer fitting selection.

## Step 6 — graph-native materialization

`cad_engine/mechanical_authority_materializer_v19.py` does not calculate or reroute. It consumes only the enriched execution graph. The legacy v17 renderer remains a compatibility shell for sheet frames, copied architecture and supporting content. Within approved plan boards, legacy route-layer entities are replaced by the authoritative v19 network segments.

Each graph-native LWPOLYLINE carries `ENGITOOLS_V19` XDATA containing the network edge ID, calculation ID, system, size and material. The exact saved DXF is reopened and every drawable authoritative segment must be found exactly once. Missing, duplicate or unknown graph-native segment identities fail the transaction and restore the prior artifact.

## Anti-overfitting and release policy

The reference corpus remains comparison-only. Recurring 2% slope labels, 16/20/25/32 mm pipe annotations, equipment capacities, or any other observed project values are not authority. Numeric design values require an explicit project basis, applicable code/standard, or governed manufacturer evidence.

Passing steps 4–6 does not by itself make a project Submission Ready. Manufacturer, structural/RCP coordination, detail/riser/schedule consistency, engineering acceptance, quality targets and golden/release gates remain mandatory. Missing authority input is reported as `INPUT_REQUIRED`, not inferred.
