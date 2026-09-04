# Mechanical pre submission release 19.1.0

Release 19.1 uses an architecture-only Pre-Submission operating profile until
Structural/RCP inputs become available. Missing structural data does not stop
draft generation, but the output is permanently marked `PRE_SUBMISSION`,
`NOT_COORDINATED`, and `NOT_MANUFACTURER_CONFIRMED`. It cannot be represented
as Submission Ready. Malformed supplied data and real QA failures remain
fail-closed.

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

## Production runtime authority

The website stamps every mechanical design request with the complete active
version manifest and PMM v2 input contract. The active `main_v19` service
rejects a stale or missing stamp, runs all v19 preflight phases, and only then
invokes the stable drawing compositor. Every successful report returns the
versions actually executed; the website rejects the artifact if analysis,
design or verification differs from its active version.
