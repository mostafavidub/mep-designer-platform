# Water network, pump and tank calculation contract

Status: governed by MEP-SIZE-001 and MEP-SUBMIT-001.

## Segment sizing

Cold- and hot-water segments are sized from explicit downstream fixture units,
a project-authorized probable-flow curve, candidate internal diameters, velocity
limit, pressure-gradient limit, material coefficient, route length and fitting
equivalent length. Every result carries a deterministic calculation ID.

The drawing entity for a segment must satisfy size_source = calc_id and
drawing_dn_mm = selected_dn_mm.

Diameter changes are independent REDUCER entities connected to the upstream
and downstream segment IDs and both source calculation IDs. Missing curves,
limits, fixture units, route lengths or fitting lengths produce INPUT_REQUIRED;
a noncompliant diameter or drawing mismatch produces FAIL.

## Water service duty

The critical path is an explicit ordered set of calculated segment IDs. Required
head is the sum of static head, critical-path friction, meter loss, valve loss
and residual fixture pressure. Utility pressure is subtracted only for an inline
booster. A break-tank pump uses the declared suction head at the tank and never
silently credits upstream municipal pressure.

The pump schedule receives the calculated operating point Qdesign/Hdesign.
Tank volume is calculated from declared occupants, demand per person, autonomy
and reserve factor. The selected volume must be explicitly supplied and may not
be below the requirement.

Reference values such as 500 L, 17 m or 17.5 GPM are held-out comparison facts,
not default design inputs. Missing external design basis remains
INPUT_REQUIRED/PRE_SUBMISSION.
