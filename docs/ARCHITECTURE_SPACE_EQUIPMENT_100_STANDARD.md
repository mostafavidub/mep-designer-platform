# Architecture Space and Equipment Recognition 100 Standard

The exact approved architectural DXF is hashed and reopened. Recognition must pass
eighteen controls: source identity; unit/scale/north/origin/bounds calibration;
deterministic frame typing; level/view binding; wall reconstruction; openings and
vertical/structural objects; closed spaces; multilingual label binding; room-use
classification; shaft/wet-core recognition; block/geometry/layer/text/spatial object
recognition; existing/proposed/non-equipment status and confidence; type/orientation;
host/level/point/port binding; view-aware deduplication; semantic spatial consistency;
per-frame visual overlays; and exact-source completeness.

Every space requires stable ID, level, closed polygon, use, area, height, centroid,
entrances, adjacency and evidence. Every recognized fixture/equipment object requires
stable ID, status, confidence, type, orientation, level, host space, point, ports and
evidence. Missing evidence is `INPUT_REQUIRED`; contradictory geometry, ambiguity,
false merges, wrong hosts or reference contamination is `FAIL`. Only all controls
`PASS` and score 100 permit release. Mechanical reference drawings are comparison-only
after blind generation and never repair recognition evidence.
