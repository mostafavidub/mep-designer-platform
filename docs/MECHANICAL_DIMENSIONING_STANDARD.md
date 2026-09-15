# Mechanical Dimensioning Standard

**Status:** LOCKED  
**Rule:** `MEP-DIMENSION-001`  
**Canonical engine:** `cad_engine.mechanical_dimensioning`

## Purpose and authority boundary

Mechanical dimensions shall make installation locations and coordinated
geometry measurable without fabricating design information.  The generator
uses only the approved architectural input, the canonical PMM/network/equipment
model and the frozen drawing manifest.  A mechanical reference drawing is never
an input to generation.

Source architectural dimensions are immutable evidence.  Generated mechanical
dimensions use dedicated `ENGITOOLS-M-DIM-*` layers and `ENGITOOLS_DIM` XDATA;
cleanup, annotation repair and later materialization may not silently convert,
delete or reinterpret them.

## Applicability and selection

The dimension contract applies to architectural plan boards for roof,
sanitary/vent, water, heating, gas, split AC and exhaust.  Cover, notes,
calculations, schedules and schematic-only boards are not falsely reported as
missing plan dimensions.

Targets are selected deterministically from owner-linked equipment, shafts and
canonical route terminals.  Equipment has first priority, vertical connections
second and route terminals third.  Duplicate owners are suppressed.  The
engine deliberately limits dimensions to a readable, non-repetitive set; it
does not dimension arbitrary drawing fragments.

Every selected installation target is located in two independent axes from the
approved source-plan datum when both distances are nonzero.  Zero-length
dimensions are forbidden.  Clearance, penetration, sleeve, route length,
elevation and slope dimensions may be generated only when the corresponding
authoritative engineering value and owner identity exist.

## Units, scale and numeric truth

Unit authority is, in order: approved architectural analysis, dimension-based
source correction and then a recognized DXF header unit.  Unknown or
contradictory units produce `INPUT_REQUIRED`; they never trigger a guessed
measurement.  Each board must have one uniform scale and a reversible source
transform.  Displayed millimetres are calculated as:

`source distance × effective source-unit-to-metre × 1000`

The DXF scale factor is derived from the same effective unit and board scale.
Exact-file QA independently recomputes the result with a tolerance of 1 mm or
0.2 percent, whichever is larger.

## CAD and graphic requirements

- Standard style: `ENGITOOLS_MECH_DIM`.
- Generated layers: installation, route, clearance and level dimensions.
- Minimum plotted text and arrow size: 0.09 board units for the canonical A4
  composition.
- Definition and dimension-line points remain inside the sheet board and must
  not occupy the title block.
- Identity, owner, sheet, family, kind and expected numeric measurement are
  embedded as XDATA on the real DXF `DIMENSION` entity.
- Semantic identifiers are deterministic across identical reruns.

## Exact-file release gate

After the final drawing mutation, QA reopens the delivered DXF and inspects the
actual dimension entities.  Release fails for missing XDATA, absent expected
entities, duplicate identities, orphan owners, nonfinite or zero measurements,
numeric mismatch, missing board identity or geometry outside the board.  A
Pre-Submission drawing may disclose missing authoritative dimension inputs; a
Submission Ready drawing cannot pass while a required dimension is incomplete.

## Required regression evidence

Positive tests cover correct unit/scale conversion, real DXF entities, semantic
ownership, architectural-dimension preservation and exact reopen.  Destructive
tests cover unknown units, missing targets, zero axes, numeric tampering,
unknown owners, duplicated identities and out-of-board definition points.
Determinism and non-applicable sheet behavior are also mandatory.
