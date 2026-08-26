# Fixture & Equipment Detection Standard

Rule Book version: 2.3 — Multi-Signal Fixture & Equipment Detection

## Objective

Mechanical design must not interpret `fixture count = 0` as evidence that a project contains no fixtures merely because CAD block names are non-standard, numeric, exploded, Persian, or consultant-specific.

Fixture and equipment recognition is therefore evidence-based and multi-signal.

## Evidence sources

The detector must evaluate, where available:

1. explicit CAD block names;
2. typed layer names;
3. nearby Persian/English annotations;
4. compact symbol geometry as corroboration only;
5. legacy high-confidence detections from the proven analyzer;
6. architectural level context from the Project Mechanical Model.

No single weak source may silently create a confirmed fixture.

## Confidence states

Every recognized object carries:

- `type`;
- drawing position;
- assigned architectural level where available;
- confidence score;
- evidence list;
- status: `detected` or `candidate`.

Text-only annotations are candidate evidence because legends and notes can contain fixture/equipment names without representing installed objects.

A detection is counted by downstream design logic only when its confidence reaches the Rule Book detected threshold. Weak evidence remains available for QA or user confirmation instead of being discarded.

## Supported fixture classes

The baseline classifier includes:

- toilet / WC;
- wash basin / lavatory;
- kitchen sink;
- shower;
- bathtub;
- floor drain;
- urinal;
- dishwasher;
- washing machine.

Persian and English aliases are supported. The alias table is extendable without changing the drawing engines.

## Supported equipment classes

The baseline classifier includes:

- boiler / package;
- water heater;
- fan-coil unit;
- split indoor unit;
- split outdoor / condensing unit;
- exhaust fan;
- AHU;
- chiller;
- pump;
- storage tank;
- gas cooker;
- kitchen hood.

## Geometry rule

Geometry must never decide fixture/equipment type by itself. Compact block geometry may only increase confidence when another signal already identifies the object type or when the object is located on a relevant fixture/equipment layer.

This rule prevents doors, furniture symbols, title blocks, and unrelated compact blocks from becoming false fixtures.

## Level assignment

Detected fixtures/equipment must be assigned to the nearest compatible architectural level using the level evidence already produced by Level Detection v3 and stored in the PMM.

Level assignment must prefer the same CAD source/container when available.

## Wet-room QA condition

If architecture confirms a wet level (kitchen, bath, toilet) but no high-confidence fixture is detected on that level, the system must record:

`wet_level_without_detected_fixture:<level>`

This is an unresolved evidence condition, not proof that no fixture exists.

During the current guarded release this diagnostic is non-blocking. It is designed to become a hard pre-design QA gate once the fixture-detection benchmark suite is sufficiently broad.

## Backward compatibility

Existing high-confidence legacy block detections must be retained and merged with v2 evidence so an analyzer upgrade cannot silently delete previously recognized scope.

The detector enriches the Project Mechanical Model but does not independently alter Drawing Manifest composition in this stage.

## Release regressions

The release is blocked unless all of the following pass:

1. numeric/opaque block on a typed plumbing fixture layer is detected;
2. unknown fixture block corroborated by nearby Persian text is detected;
3. standard HVAC equipment block such as FCU is detected;
4. text-only fixture annotation remains a candidate and is not counted;
5. unrelated compact blocks such as doors are not classified as fixtures;
6. fixture/equipment detection carries confidence and evidence into the PMM;
7. wet-level zero detection produces an explicit diagnostic;
8. all pre-existing project, planner, CAD and website regression tests remain green.
