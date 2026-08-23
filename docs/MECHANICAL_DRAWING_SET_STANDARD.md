# Mechanical Drawing Set Planning Standard

## Mandatory pre-generation stage

Mechanical CAD generation must not start before Drawing Set Planning and explicit user approval.

Flow:

Architecture Upload -> Architecture Analysis -> Mechanical Questions -> Effective-Level Analysis -> Typical-Floor Analysis -> Authority Submission Sheet Planning -> Drawing Set Proposal -> User Approval -> CAD Generation

## Governing customer-facing count

The number displayed to the customer MUST equal the number of separate mechanical drawings/sheets that will actually be issued for approval and delivery.

For the local Engineering Organization submission profile, different mechanical disciplines MUST NOT be merged merely to reduce sheet count. A combined internal CAD view is not the same thing as an approval deliverable.

Therefore the previous composition rule that merged water+gas, heating+cooling, or sanitary+rainwater into one customer-counted sheet is retired for the authority-submission profile.

## Authority-separated deliverable families

The default mechanical approval set is separated into these deliverable families:

1. Water supply — cold/hot water and associated water-supply equipment/schematic.
2. Sanitary + vent — sanitary drainage and vent.
3. Heating — heating distribution only.
4. Cooling/HVAC — cooling distribution, condensate and required equipment/roof sheet.
5. Gas — gas piping only.
6. Ventilation/exhaust — mechanical ventilation and exhaust only.
7. Roof/rainwater — dedicated roof drainage plan.

Riser, equipment, calculation and legend information must be placed inside the relevant system family unless a project/authority rule explicitly requires an additional dedicated sheet. A generic extra M-RISER-CALC sheet must not be added by default because it changes the approved deliverable count.

## Effective Levels

A system is active only on levels where that system has a real design requirement. Effective Levels must be determined per system from architecture and resolved project inputs.

- Cooling: conditioned levels. Required outdoor/equipment level is counted as a special cooling sheet when applicable.
- Heating: heated levels only.
- Water Supply: levels with plumbing consumers. Multi-level projects also receive the required water-supply riser/equipment/schematic sheet.
- Sanitary/Vent: levels with sanitary fixtures/drainage scope.
- Ventilation/Exhaust: levels requiring mechanical ventilation/exhaust.
- Gas: levels with gas consumers when gas is enabled.
- Roof/Rainwater: one dedicated roof drainage sheet where roof drainage is required.

A level must never be included just because it exists architecturally, except for a required system-specific special sheet (for example roof cooling equipment or a water riser/equipment sheet).

## Typical Floor rule

Typical-floor detection remains mandatory, but it is system-specific and must never be used to combine different systems.

Two or more levels may share one Typical Floor sheet for a given system only when all relevant characteristics match:

- architecture geometry and room arrangement;
- wet-core location where relevant;
- shaft/vertical reference positions;
- fixture/consumer distribution;
- equipment/load positions;
- the system-specific routing pattern.

If any of these materially differs, separate sheets are required. The authority-submission profile is conservative: when Typical equivalence is uncertain, keep separate sheets.

## Reference authority-approved drawing set

The supplied approved mechanical reference contains exactly 21 title-block drawing frames (`kadrr56`) in Model Space. The 21 sheets are organized by drawing-code families as follows:

- Mech-04: 1 roof/rainwater sheet.
- Mech-05_1..3: 3 sanitary + vent sheets.
- Mech-06_1..4: 4 water-supply sheets, including the system special/riser/equipment sheet.
- Mech-07_1..3: 3 heating sheets.
- Mech-08_1..3: 3 gas sheets.
- Mech-12_1..4: 4 cooling/HVAC sheets, including the required equipment/roof sheet.
- Mech-13_1..3: 3 ventilation/exhaust sheets.

Reference total:

1 + 3 + 4 + 3 + 3 + 4 + 3 = 21 deliverable sheets.

This reference is the regression benchmark for the authority-submission profile. It demonstrates why the old 13-sheet combined-family interpretation was incorrect: that interpretation merged approval disciplines and also added a generic combined riser/calculation sheet that is not how this approved set is organized.

## Calculation principle

For each system family:

1. determine its Effective Levels;
2. apply verified system-specific Typical Floor consolidation only when allowed;
3. count one separate deliverable sheet per remaining system-level pattern;
4. add required system-specific special sheets;
5. add the dedicated roof/rainwater sheet where required;
6. do not add a generic combined riser/calculation sheet unless explicitly required.

Customer Deliverable Sheet Count = sum of all authority-separated system-family sheets and required system-specific special sheets.

The customer-visible count and the final CAD deliverable count MUST be the same semantic quantity.

## Proposal contract

The proposal must show:

- each deliverable system family;
- exact sheet count per family;
- level or Typical Floor represented by each sheet;
- any system-specific special sheet;
- exact total deliverable sheet count;
- approval state.

The UI must never present an internal combined-family count as the customer deliverable count.

## Approval Gate

The customer must approve the exact authority-submission drawing list before mechanical CAD generation starts. If the list changes, approval is invalidated and must be obtained again.
