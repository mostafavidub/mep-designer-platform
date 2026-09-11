# Mechanical Construction-Document Delivery Standard (Steps 14–19)

## Release contract

Steps 14–19 are one fail-closed construction-delivery package. A drawing set is not
final merely because it contains labels or visually resembles a reference set. The
package may be released only when every phase below returns `PASS`.

## Step 14 — Parametric construction details

Every final detail has executable geometry and an immutable `Detail ID`. Its
identity binds the source plan, PMM entity, calculation, and—when product geometry
or limits are used—the official manufacturer catalogue record. Every Detail ID is
referenced on a plan. Preliminary-only and label-only details are prohibited.
Missing dimensions, installation requirements, valves, traps, vents, cleanouts,
sleeves, waterproofing, firestopping, clearances, bases, isolators, anchors, power,
refrigerant, drainage, flue, or combustion-air data remain `INPUT_REQUIRED` when
applicable; the engine must not invent them.

## Step 15 — CAD construction quality

The renderer reports the actual materialized inventory of required CAD primitives:
blocks, dimensions, hatches, leaders, callouts, section/detail markers, equipment,
fitting, and reducer symbols. A required type with no materialized entity blocks
release. Reference-drawing entity counts are never generation targets.

## Step 16 — Cover and drawing index

The drawing index is generated from the release Manifest. Sheet codes must be
unique, and the following identity is mandatory:

`Manifest sheets == Index sheets == DXF layouts`

Any missing, duplicate, or extra layout fails the release.

## Step 17 — Final equipment schedule

The public schedule contains `Tag`, user-facing `Level`, `Room`, `Type`,
`Manufacturer`, `Model`, `Capacity`, `Flow`, `Power`, `Connection Size`, and
`Status`. Internal plan or level identifiers are not shown as the user-facing
level. Missing fields are `INPUT_REQUIRED`; any non-PASS equipment row fails.

## Step 18 — Annotation solver

Annotation placement checks collision, leader crossing, border/equipment overlap,
and minimum printed text height. Dense areas must produce a source-bound enlarged
view rather than unreadable text. Unresolved or unreadable annotation blocks release.

## Step 19 — Submission QA hard failures

Final QA requires explicit zero evidence for missing systems, orphan fixtures,
unconnected equipment, missing segment sizes, reverse gravity slopes, plan/riser
mismatches, invalid riser levels, equipment without calculation/manufacturer
evidence, manufacturer violations, missing mandatory details or rainwater systems,
and unreadable/overlapping annotations. Missing evidence never defaults to zero.

## Compatibility and migration

The contract is additive. Existing inputs remain readable, but incomplete legacy
packages cannot be issued as final. No private reference drawing or manufacturer
value may be embedded as a hidden default.
