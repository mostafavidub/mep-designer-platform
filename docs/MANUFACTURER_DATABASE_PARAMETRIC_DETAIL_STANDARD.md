# Manufacturer database and final parametric-detail contract

Status: governed by MEP-EQUIP-001 and MEP-SUBMIT-001.

## Manufacturer database

Every selectable product record requires manufacturer, model, equipment type,
capacity, dimensions, weight, connections, electrical data, water flow, gas
consumption, refrigerant data, piping limits, clearances, sound, pressure,
pump/fan curves or explicit non-applicability, and an official manufacturer
document. The document must have an HTTPS official URL, revision, retrieval date
and SHA-256 digest. Reseller records and malformed hashes are rejected.

The repository stores only normalized semantic fields, provenance and hashes.
Private or copyrighted manufacturer binaries are not committed. Missing official
records remain `INPUT_REQUIRED`; no commercial model is fabricated.

## Parametric details

Final detail families are generated from the governed equipment/network record:

- radiator: exact dimensions, installation height, TRV, lockshield, flow/return,
  pipe DN, wall clearance and sleeve;
- ODU: exact dimensions, service clearances, base, vibration isolation, anchors,
  power isolator, refrigerant connections and drain;
- sanitary: pipe DN, trap, vent, cleanout, sleeve, waterproofing and firestop.

Every detail carries Detail ID, source Plan ID, PMM ID, Calc ID and, where
applicable, manufacturer Catalogue ID. Manufacturer dimensions must match the
registered record. Empty components, label-only output or identity mismatch
blocks final documentation.
