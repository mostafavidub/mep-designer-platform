# Step 9 — Required Scope Completeness: Septic / Fire-Water

Step 9 prevents an explicitly required mechanical system from disappearing from the issued package or being represented by a note alone.

## Current production capability

The active authority engine currently supports domestic water, sanitary/vent, heating, gas, split AC, exhaust and roof-rainwater scope. It does **not** currently issue a complete SEPTIC or FIRE_WATER design family. Therefore an explicit septic or fire-water requirement is blocked as `UNSUPPORTED` before CAD generation rather than silently omitted or faked with generic text.

## Release invariants

1. Requirement detection is explicit and fail-closed. Boolean-like strings such as `false`, `no`, `خیر` and `ندارد` do not become true merely because they are non-empty Python strings.
2. SEPTIC can be required by `septic_required`, an explicit septic wastewater-disposal basis, or an approved septic manifest family/title.
3. FIRE_WATER can be required by `fire_water_required`, `fire_fighting_required`, `fire_service_required`, or an approved fire-water/fire-protection manifest family/title.
4. An explicitly required system that is not supported by the production engine is `UNSUPPORTED` before the CAD designer is invoked.
5. The gate never invents a septic tank, fire pump, fire tank, hydrant, sprinkler, pipe route, capacity, location or calculation merely to make scope appear complete.
6. Exact-file defense in depth requires both real mechanical geometry and a readable system tag. Text, notes, titles and schedule rows alone are not materialization evidence.
7. Septic exact evidence must use real non-text geometry on an `ENGITOOLS-M-*SEPTIC*` layer plus a septic tag.
8. Fire-water exact evidence must use real non-text geometry on a mechanical layer containing `FIRE` and a fire-water component token such as `WATER`, `PUMP`, `TANK`, `HYDRANT`, `SPRINKLER` or `HOSE`, plus a readable fire-water tag.
9. If future production support is added, the exact-file artifact gate remains mandatory so a supported system cannot regress to text-only representation.
10. Step 8 calculation evidence remains upstream; Step 9 does not weaken or bypass any previous fail-closed gate.

## Status policy

- `NOT_APPLICABLE`: neither septic nor fire-water is explicitly required.
- `PASS`: all explicitly required systems are supported by the production capability set; exact-file validation separately proves materialization.
- `UNSUPPORTED`: an explicitly required system is outside the current production capability set; CAD generation is stopped before mutation.
- `FAIL`: exact-file reopen fails or required real geometry/tag evidence is missing.

The safe behavior for current production projects that require septic or fire-water is to stop and request/implement the missing system capability, not to release an incomplete mechanical package.
