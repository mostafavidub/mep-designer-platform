# Fasihi nested-block wall-source audit

## Scope and safety

This audit is limited to the authoritative Fasihi Ground and Level 01 frames at
source SHA-256 `08b2e3f2a16a90727e1ef44e8dbc96455a57a553a6f7ef6b2d0800dcadeb13ca`.
The source DXF was parsed once. P1, P3, P7, Vision, Golden annotations, Portal
development, envelope thresholds, merge, and deployment were not used.

Current runtime behavior was confirmed before classification: a nested child
reaches `_boundary_geometry_decision` with its block name as `source_block`; if
the context has no positive wall token it is rejected as
`NESTED_BLOCK_EXCLUDED`. Runtime extraction was not changed by this audit.

## Classification contract

Classification is definition- and instance-aware. Every row retains definition
identity, INSERT handle, parent/path/depth, transform, transformed bounds,
world-coordinate child geometry, child handles, entity counts, linear length,
positive evidence, negative evidence, role, status, and proposed action.

Wall admission requires all independent positive signals below and no negative
object evidence:

1. multiple connections to the existing accepted wall network;
2. plausible local parallel wall faces/thickness;
3. room-scale extent;
4. predominantly linear geometry; and
5. material-length evidence.

Names/layers are supporting context only. Doors, windows, openings, fixtures,
casework, furniture, annotation, text glyphs, and detail graphics can never enter
the wall pipeline through this classifier. Unknown stays excluded. A supported
negative parent role prevents a descendant from being silently promoted.

## Definition and instance results

| Floor | Definition | Instances | Result | Action |
|---|---:|---:|---|---|
| Ground | `_Oblique` | 2 | text-glyph graphic | exclude |
| Ground | `rgrg` | 1 | unknown; zero external wall connections | keep excluded/unresolved |
| Ground | `THH` | 1 | detail graphic with ARC/DIMENSION/HATCH/MTEXT | exclude |
| Ground | `23r` | 2 | small curve-rich object/furniture geometry | exclude |
| Ground | `TBL6L` | 1 | furniture; 26 ARC + 2 CIRCLE | exclude |
| Level 01 | `_Oblique` | 2 | text-glyph graphic | exclude |
| Level 01 | `rgrg` | 1 | unknown; zero external wall connections | keep excluded/unresolved |
| Level 01 | `23r` | 5 | small curve-rich object/furniture geometry | exclude |

Ground contains 7 intersecting instances: 6 supported non-wall, 1 unresolved,
0 proven wall assemblies. Level 01 contains 8: 7 supported non-wall, 1
unresolved, 0 proven wall assemblies. The two unresolved `rgrg` instances have
local parallel geometry but no external wall-network connection, so they fail
the positive wall gate and remain excluded.

## Decision

`are_nested_blocks_a_dominant_missing_wall_source = NO`

Exact status: `NESTED_BLOCKS_NOT_DOMINANT_WALL_SOURCE`

No nested child geometry is admitted. No envelope rerun is warranted because the
same extraction input is intentionally preserved. The previous Fasihi envelope
status therefore remains `INPUT_REQUIRED`; changing it would be false evidence.
The next investigation must target a different source of missing wall evidence,
not broad nested-block enabling.

## Reproducibility and artifacts

Run:

```text
PYTHONPATH=. python3 tools/architectural_nested_block_qa.py SOURCE_DXF BASELINE_MODEL OUTPUT_DIR
```

The tool writes `nested-block-inventory.json` and six overlays per floor:
raw nested geometry, role classification, admit/reject, external connectivity,
local thickness, and final decision. Private source drawings and generated
customer artifacts are not committed.
