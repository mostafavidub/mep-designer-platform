# Mechanical Design Basis Contract

Active contract: `mechanical-design-basis-v18.5.3`
Platform release: `18.5.7`

Mechanical design is fail-closed before queueing and again at the CAD authority
boundary. The website, persisted project answers and CAD engine use the same
canonical fields for city, rainfall intensity, service pressures and mechanical
shaft authorization.

The active authority output supports wall-mounted split AC. The website must
offer that exact supported choice, store it as `wall_mounted_split_ac`, and use
the same canonical value in CAD. Ducted split, VRF/VRV, chiller/fan-coil and
evaporative cooling remain explicit unsupported inputs until their own complete
equipment, routing, sizing and release gates exist; they may never be silently
substituted or reported as a missing answer.

## Required behavior

- Preserve the user's raw answer and store its canonical value.
- Offer only authority-supported cooling systems and reject unsupported text
  with a clear customer-facing explanation before design starts.
- Accept `city` and legacy `location` as input aliases; persist `city`.
- Parse Persian, Arabic and Latin numeric rainfall values into
  `rainfall_intensity_mm_h` without inventing a default.
- Store shaft authorization as a structured approval with strategy, source,
  timestamp and contract version.
- Bind each generated shaft proposal to its plan id and approved point.
- A request to use existing architectural shafts never authorizes an invented
  shaft when none was detected.
- Commit and reload every answer before permitting workflow advancement.
- Missing authority inputs return the project to `INPUT_REQUIRED`, preserve the
  architectural analysis, and resume at `authority_contract` after completion.
- Legacy cooling failures reopen the exact supported-cooling question once and
  clear only the invalid cooling answer; architectural analysis is retained.
- Raw QA dictionaries, filesystem paths and stack details are admin-only and
  must never be rendered in customer pages or flow responses.

## Release gate

Positive, negative, persistence, HTTP flow, recovery, web UI, version-sync and
full regression tests must all PASS. A missing, skipped or unknown result blocks
merge and deployment.
