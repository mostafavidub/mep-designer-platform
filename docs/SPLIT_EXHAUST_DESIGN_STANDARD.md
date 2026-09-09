# Split AC and exhaust final-design contract

Status: governed by MEP-SIZE-001, MEP-EQUIP-001 and MEP-SUBMIT-001.

## Split AC

Final cooling load requires room area, orientation, glazing, external wall,
occupancy, lighting, equipment, infiltration, ventilation, indoor/outdoor design
temperatures and explicit thermal/solar coefficients. Room results aggregate to
zones through a declared diversity factor; no held-out reference capacity is a
design default.

Every IDU output carries calculated load, selected capacity, margin,
manufacturer/model, airflow, refrigerant sizes, route length, elevation,
condensate status and official revisioned datasheet hash. ODU selection checks
connected ratio, total pipe length, elevation and service clearance. Missing or
incompatible evidence remains `INPUT_REQUIRED` and cannot be issue-ready.

## Exhaust

Every applicable WC, bathroom, utility, kitchen or enclosed service room must
have an explicit project criterion expressed as ACH and/or minimum CFM. Fan duty
uses the greater airflow requirement and sums declared duct, fitting and terminal
losses as ESP.

The selected official fan must satisfy both airflow and ESP. Each schedule row
retains its calculation ID, manufacturer/model and selected duty. Any applicable
room without a compliant fan produces `UNSERVED_EXHAUST_ROOM` and fails the
release gate; `unserved exhaust room = 0` is mandatory.
