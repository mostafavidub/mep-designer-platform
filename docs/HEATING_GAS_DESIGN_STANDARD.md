# Heating and gas design contract

Status: governed by MEP-SIZE-001, MEP-EQUIP-001 and MEP-SUBMIT-001.

## Heating

### Professional Pre-Submission heating chain

An explicitly confirmed total project heating load may be used to recover a
useful Pre-Submission design when the architectural room identities are valid
but reconstructed room areas are demonstrably degenerate.  The engine must:

- disclose the invalid raw room-load total and the confirmed project total;
- allocate the total deterministically by documented room-type weights;
- preserve every room, radiator, route and calculation identity;
- reconcile the sum of room duties exactly to the confirmed total;
- size both flow and return branches from terminal duty and declared fluid
  properties, design temperature difference, velocity and friction limits;
- expose flow, DN, velocity, Reynolds number, friction gradient, equivalent
  length and relative pressure loss for every branch; and
- fail when any heatable room is unserved, any radiator is orphaned, any route
  leaves its plan, any hydraulic limit has no compliant diameter, or the load
  balance does not reconcile.

This recovery is a `DESIGN_ENVELOPE` only.  It must remain `PRE_SUBMISSION` until
the project envelope/design-day inputs, exterior-wall/window placement, official
manufacturer radiator records, package/DHW duty and independent engineer review
are complete.  A recovered preliminary design must never satisfy the final
manufacturer or Submission Ready gates.

Every room radiator is selected from an official, revisioned and hash-identified
manufacturer record at the declared supply, return and room temperatures. The
output records the room heat loss, exact model, section count, selected output
and physical dimensions. A generic preliminary kW label cannot satisfy final QA.

The package is selected against space-heating demand, DHW design demand and an
explicit simultaneous-demand factor. Space, DHW and combined capacities must all
pass. Gas consumption is taken only from the selected official record.

Heating supply and return segments accumulate selected downstream radiator
output. Flow, velocity, DN and Calc ID are derived from explicit fluid properties,
design delta-T, candidate diameters and velocity limit. Drawing DN must retain
the segment calculation identity.

## Gas

Every gas appliance requires manufacturer, model, thermal input, gas consumption,
official datasheet provenance, terminal shutoff, flue and combustion-air evidence.
Every segment records cumulative gas flow, equivalent length, service pressure,
allowable pressure drop, selected DN, Calc ID and size source.

Pipe DN is selected only from the supplied authority/code capacity table.
The executable system contains meter, regulator, appliance shutoff, flue and
combustion-air components. Missing evidence is INPUT_REQUIRED; no capacity-table
match or drawing/calculation mismatch is FAIL.

Project-10/Fasihi values remain held-out semantic comparison facts and are never
used as hidden defaults.

## Target-sheet issue gate

M-131/M-132 are final only when each room has a PMM identity, an envelope and
outdoor-air heat-loss calculation, declared supply/return temperatures, an exact
official radiator model/size and a non-preliminary package selection. M-141/M-142
are final only when every segment carries Flow + Leq + DN + Calc ID and the
package includes meter, regulator, service shutoff, appliance valves, riser,
fittings, sleeves, flue and combustion-air evidence. Any absent value is
`INPUT_REQUIRED`; no preliminary radiator may appear in an issued package.
