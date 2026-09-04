# Mechanical Design Basis Contract

Active contract: `mechanical-design-basis-v18.5.2`
Platform release: `18.5.2`

Mechanical design is fail-closed before queueing and again at the CAD authority
boundary. The website, persisted project answers and CAD engine use the same
canonical fields for city, rainfall intensity, service pressures and mechanical
shaft authorization.

## Required behavior

- Preserve the user's raw answer and store its canonical value.
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
- Raw QA dictionaries, filesystem paths and stack details are admin-only and
  must never be rendered in customer pages or flow responses.

## Release gate

Positive, negative, persistence, HTTP flow, recovery, web UI, version-sync and
full regression tests must all PASS. A missing, skipped or unknown result blocks
merge and deployment.
