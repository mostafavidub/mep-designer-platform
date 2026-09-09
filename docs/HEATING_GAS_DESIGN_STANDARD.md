# Heating and gas design contract

Status: governed by MEP-SIZE-001, MEP-EQUIP-001 and MEP-SUBMIT-001.

## Heating

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
