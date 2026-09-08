# Step 8 — Calculation Evidence / Utility Pressure Traceability

Step 8 prevents a numeric utility-water pressure from entering mechanical calculations unless it is traceable to an explicit project input.

## Release invariants

1. Approved water scope requires explicit project water-pressure evidence before the active CAD designer is invoked.
2. Accepted pressure must parse to a finite, strictly positive numeric value.
3. Supported aliases are `water_inlet_pressure`, `water_pressure`, `water_inlet_pressure_bar`, and `utility_water_pressure`; aliases that are simultaneously present must agree numerically.
4. Structured values marked as assumed, default, benchmark, placeholder, or preliminary are never promoted to project evidence.
5. Benchmark values such as the v17 completeness-test water pressure may remain diagnostic assumptions, but they cannot become `PROJECT_INPUT` or final utility-pressure evidence.
6. Missing required pressure is `INPUT_REQUIRED`; invalid, non-positive, assumed-as-final, or contradictory values are `FAIL`.
7. Canonical `water_inlet_pressure` / `water_pressure` numeric aliases are written only after Step 8 passes, together with `_water_pressure_evidence` provenance.
8. Step 8 runs before coordination and before the legacy CAD designer in the active v19 adapter, so a failing pressure contract cannot mutate the output DXF.
9. The exact generated-artifact calculation check remains defense in depth and must still reject a numeric utility-pressure statement that has no project evidence.

## Status policy

- `PASS`: an explicit consistent project pressure is available and is safe to pass to calculations.
- `INPUT_REQUIRED`: approved water scope exists but no project pressure was supplied.
- `FAIL`: supplied pressure is invalid, non-positive, assumed/default/benchmark, or contradictory across aliases.
- `NOT_APPLICABLE`: no approved water scope and no pressure answer exists.

The gate does not invent a utility pressure, convert a completeness-test assumption into a project fact, or select a pump duty from missing pressure evidence.
