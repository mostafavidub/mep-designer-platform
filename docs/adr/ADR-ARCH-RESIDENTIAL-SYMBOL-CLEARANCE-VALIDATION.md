# ADR — Canonical residential symbol clearance and placement validation

## Problem

The residential foundation can generate 41 deterministic reference footprints but
cannot represent asymmetric typed clearance evidence or independently validate
placement, collision, door operation and a bounded access path. Treating a valid
footprint as usable or compliant would overstate authority.

## Decision

Extend `cad_engine.residential_symbols` rather than create another symbol engine.
Represent clearances as source-bound data profiles and placements as exact
project/space/host/transform dependencies. Add a separate read-only validator that
consumes these contracts, performs no repair, and preserves geometry, usability,
regulatory and professional states independently.

Mandatory profiles require an independent authority-resolver interface. This change
defines the interface but supplies no trusted production registry or credential
provider. Synthetic data cannot qualify authority.

## Consequences

- All existing symbol IDs and consumers remain compatible.
- Unknown mandatory evidence fails closed.
- Clearance overlap is evaluated by an explicit coexistence policy.
- Access checking is bounded to supplied room/obstacle geometry.
- Runtime, Generator, CAD insertion and whole-plan QA remain disabled.
- Existing records can be retained and revalidated; no destructive migration is
  necessary.

## Rejected alternatives

- A new versioned symbol or CAD engine.
- A single universal clearance distance.
- Promoting owner/manufacturer/ergonomic values into code authority.
- Nearest-host inference or geometry repair.
- Treating all overlaps as either automatically permitted or automatically invalid.
