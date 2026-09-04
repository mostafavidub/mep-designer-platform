# Mechanical coordination release 19.0.0

Release 19 introduces four ordered, fail-closed gates. A non-PASS result stops
the transaction before the next phase. `FAIL`, `SKIPPED`, `MISSING`, `UNKNOWN`,
`INPUT_REQUIRED`, and `PRE_SUBMISSION` never authorize issue, merge, or deploy.

1. Structural/RCP coordination stores source-hashed beams, columns, slabs,
   ceilings, shafts, service zones and forbidden zones in a shared 3D datum.
   The 2.5D router compares orthogonal candidates across permitted elevations
   and validates clashes, penetrations, clearance and gravity slope.
2. Manufacturer selection accepts only revisioned official datasheets. It
   checks calculated capacity, dimensions, connections, clearance, maximum
   route/elevation, pump head and fan flow. Missing evidence yields a Design
   Envelope marked `PRE_SUBMISSION`, never a fictional model.
3. Details contain executable geometry, dimensions, fittings, material,
   clearance and tags. Risers are generated from the network graph, enforcing
   `Plan ID = Riser ID = Calc ID = Schedule ID` with zero mismatch.
4. Golden projects 1, 3, 4, 6, 7, 8 and 10 are generated from architecture
   only and hash-sealed before any reference comparison. Thresholds are score
   >= 70, score drop <= 0, and pass rate = 100%.

Private customer drawings and generated customer DXFs are never committed.
Only hashes, semantic metrics and reproducibility metadata may enter baselines.
