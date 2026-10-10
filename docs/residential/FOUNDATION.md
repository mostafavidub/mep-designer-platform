# Residential architecture foundation 0.2.0

Status: **ARCHITECTURE_FOUNDATION_RESEARCH_REQUIRED**. The original catalogs remain **ARCHITECTURE_FOUNDATION_PARTIAL** and source qualification remains **ARCHITECTURE_RULEBOOK_INPUT_REQUIRED**. This is an offline research/contract foundation, not a released plan generator. It is reintegrated after Canonical Architecture 3.1 without changing text, geometry, separator, portal, shaft, scale, north or Q02 authority. No customer activation, pricing action, mechanical authority, sealed Pilot output or accepted Golden is changed.

## Seven deliverables and exact limits

| Deliverable | Canonical artifact | Current qualification |
|---|---|---|
| Architecture Rulebook | `data/rulebook/architecture/rulebook.json`, `research-completion.json` | 32 extracted M4 hard-rule clauses audited for extraction, all disabled for release; all 24 gaps have an explicit resolution class. Significant authority coverage remains missing. |
| Exam source coverage | `exam-coverage.json`, `sources.json` | Ten candidate topics; current official list not verified, denominator unknown, percentage null. |
| Public-plan study | `plan-study.json`, `heuristics.json` | 122 visually inspected distinct floor/layout records, 74 projects; 22 context-only/partial/multilevel examples. Qualitative, not dimensional certification. |
| Original symbols | `symbols.json`, `cad_engine/residential_symbols.py` | 41 parametric references; four manufacturer footprint examples; most normative/ergonomic dimensions and operating clearances unresolved. |
| Owner requirements | `owner-questionnaire.json`, `owner-program.schema.json`, additive v2 draft/resolved schemas | 58 Persian questions:13 mandatory,8 conditional,37 optional;13 auto facts. V1 remains unchanged. Offline Owner Program 2.0 adds per-field provenance, deterministic conflicts, migration findings and fail-closed authority bindings without runtime activation. |
| QA matrix | `qa-matrix.json` | 104 planned engine scenarios, not 104 executed tests. Actual foundation regressions separately reported. |
| Generation contract | `generation-contract.json`, input/output schemas | Version0.2.0;15-stage constraint-first workflow. Input preflight and ranking guards are implemented; candidate search and complete independent layout validator are not implemented. |

All eleven catalogs have Draft2020-12 structural schemas under `standards/test-suites/residential/`; a separate Owner Program schema is also included. Tests audit source references, the 32-rule inventory, 24 gap classifications, authority isolation, unique record hashes, evidence frequencies, geometry, input typing, branches and quality gating. Schemas are not a claim of legal completeness.

## Scope and repository reuse

V1 is residential apartment floor plans with an explicit identical residential-floor schedule. Parking dependencies, cores, shafts, wet areas, equipment access and known structural reservations constrain the floor plan, but this foundation does not design parking, structure, MEP systems, facades, sections or roofs.

Canonical Architecture3.1 remains the recognition/evidence authority. Residential Foundation is design knowledge only. Text cannot create walls, rooms, separators, portals, shafts or engineering geometry and cannot grant scale or north authority. Q02 remains fail-closed. Generated proposals need a future generated-origin adapter; invented source handles or DXF witnesses are forbidden. Existing `architecture_validator` and snapshot gates cannot be replaced with this preflight. Mechanical fixture/basis questionnaires remain separate. This foundation does not write PMM, billable area or a quote.

## Source audit and release qualification

M4 clauses were visually checked against PDF pages60,61,66–75,98–101. Numeric text extraction has font-mapping errors, so extracted digits alone were not used as rule authority. Source coordinates are explicit PDF and printed-page numbers. Applicability text and exceptions must be reviewed against the complete project-specific rule inventory before any rule is enabled. General room minima do not supersede occupancy-specific requirements.

The supplied M3 copy is1392; a separate local1395 third-edition cover was verified. Full1395 egress extraction and official errata remain missing. M15 cover is1392; definitions and general applicability were reviewed, but complete lift-trigger/cabin/landing extraction is pending. M18 filename says1402 but cover and committee page say1396; the scanned copy needs further page review for acoustic criteria. M19 cover is1399 fourth edition; current official IRCEO notices report fifth edition1404 and concurrent implementation of both editions through1405-12-29. A project must resolve the applicable edition/permit profile; the fourth edition is not automatically obsolete.

- [Official M19 transition notice](https://irceo.ir/fa/news/36375/تمدید-اجرای-همزمان-ویرایش-چهار)
- [Official fifth-edition announcement](https://irceo.ir/fa/news/36052/ابلاغ-ویرایش-پنجم-مبحث-نوزدهم)
- [Official exam portal attempted](https://inbr.ir): unavailable to research tool; secondary lists only identified candidates and were not used as official authority.

Security appendix: user year1402 versus publicly indexed1403 document lead is unresolved. The candidate Tasnim-hosted primary-document download failed certificate validation; it was not treated as inspected. Disability/accessibility1399 third edition and official amendments are still required. Current municipal/parcel permit instructions, local setbacks/parking/accessibility/fire interpretation, and current official exam notice are absent. Do not guess them or mark the ten-topic discovery list complete.

The matrix also explicitly defers non-plan execution details and escalator design outside V1. Source document review is partial, not an assertion that all322 M19 pages or all supplied PDFs were fully reviewed.

## Study method and additional design knowledge

122 records are actual visual reviews, not search hits. Exact duplicate hashes and visual overlays were excluded. Composite sheets count one identified floor; identical repeated floors count once. Genuinely distinct floors and renovation before/after are separately labeled. No copyrighted plan, private CAD, traced geometry or source PDF is committed. The ledger stores URL, image hash, view, original observation, risk and normalized attributes; null means unverified.

Publication diversity is limited to ArchDaily galleries, though74 projects have independent architectural contributors across16 known countries;18 records have unknown country metadata. This is a convenience sample, not a representative survey. Repeated floors are correlated, so heuristic frequency counts distinct projects as well as plans. Iran/international support is reported per heuristic; international dimensions never become Iranian rules.

There are21 deduplicated patterns:18 repeated-project soft heuristics and3 single-project reference patterns. Service clustering appears in46 projects, sleeping-zone separation35, central core23, living/terrace relationship16, and opposite-edge exposure13. These counts describe visible arrangements, not measured performance. Entry buffers and daylight patterns overlap existing M4 concepts; their observed arrangement is additional evidence, not a new legal rule. Fixed-core flexibility, kitchen/terrace adjacency and separate service entry remain too weak for broad generalization.

Rejected generalizations: publication implies compliance; every room rectangle is a bedroom; identical core means identical floors; drawn furniture proves usable clearance; wet adjacency proves stacked shafts; terrace/void equals enclosed area; an international compact apartment establishes Iranian minimum area. Study observations are not human-reviewed Golden truth.

## Parametric reference geometry

41 symbol categories cover sanitary fixtures, kitchens/appliances, beds/storage/desks, seating/dining, vehicles, doors/windows/stairs/lifts/shafts. Geometry is original code. Caller supplies metres, anchor, rotation and dimension basis. Actual object footprint, front usage clearance and door operating sweep are separate. Unknown usage clearance blocks fit approval. Generic rectangles are conservative placeholders, not manufacturer outlines. No fabricated plumbing ports are emitted.

Four sourced product examples illustrate the distinction: IKEA MALM160×200 mattress has176×209cm overall frame; Duravit D-Code251309 wall WC has370×540mm footprint,034265 washbasin650×485mm,720163 shower tray700×1600mm. These are specific products, not ergonomic minima or automatic defaults. Usage/maintenance envelopes remain unknown until qualified.

- [IKEA product dimensions](https://www.ikea.com/fi/en/p/malm-bed-frame-high-white-s09929373/)
- [Duravit product catalog](https://www.duravit.co.uk/file/8a8a818d9227d0b10192290806020627.uk-en.0/d-code_brochure_2024_uk.pdf)
- [Duravit series products](https://www.duravit.com/en-en/products/all-series/d-code/)

CAD strategy: metre-native original blocks on object/usage/port layers; explicit symbol/catalog/parameter/instance/build identity; no INSERT into customer CAD before host, fit, scale and exact reopening checks. Current export is SVG only; DXF integration is specified, not implemented.

## Owner model

The master questionnaire separates purpose, unit mix, required room counts, reception/kitchen style, sanitary program, privacy, accessibility, storage, laundry, furniture, balcony and equipment reservations. City/parcel/climate/permit facts are not asked redundantly when supported by authoritative project input. Owner preference cannot override law.

V1 asks13 essentials first, then8 conditional branches only when activated, then37 optional refinements. Answers need project/revision/scope/owner confirmation and a stable hash; changes invalidate dependent candidates, metrics and review. Mandatory unknowns block. Optional unknowns remain unscored; no hidden defaults. Unit counts/types/ranges have cross-checks. Other complex structured preferences currently require manual contract review; this is not a complete deployable questionnaire service.

Owner Program 2.0 is an additive offline contract. `OwnerProgramDraft` can preserve a
valid incomplete brief before site or local authority is available; `DRAFT_VALID` does
not mean generator-ready or geometrically feasible. The draft owns the one canonical
unit program and records the exact value and provenance for every material field.
`ResolvedGenerationInput` stores the draft and unit-program hashes and binds exact
site, national-ruleset and local-profile identities, versions, source references and
hashes. Resolution separately requires a complete unit program, verified compatible
material provenance, an independent current-binding snapshot and evidence-backed
geometry feasibility; embedded `VERIFIED` flags alone grant no authority. Resolved
project/program identity and stored status are recomputed against the source draft.
Accessibility owner preference/needs and regulatory applicability have separate
provenance; only national/local code evidence can establish applicability. Geometry
evidence is bound to a deterministic fingerprint of the draft, canonical unit program,
site and authority snapshots, and must match a separately supplied current evidence
record. The trusted evidence registry remains a future integration gate.
Missing local authority returns `LOCAL_RULE_REQUIRED`; changed bindings return
`STALE_BINDING`; geometry not yet checked returns
`NEEDS_GEOMETRIC_FEASIBILITY_CHECK`. V1 read/write and questionnaire behavior remain
unchanged. The migration adapter preserves the complete v1 payload and marks unknown
legacy provenance explicitly. Neither v2 contract is imported by the production
runtime or enables the Generator.

Local jurisdiction qualification is also an additive offline contract. A
`LocalRuleProfile` records exact official-document identities, temporal and
jurisdiction scope, clause-level local rules and bounded review. A separate
`ProjectCodeBasis` binds that profile to the exact project, parcel, Site Model,
Owner Program, national profile and permit/design date. Synthetic profiles can prove
contract behavior only and are capped at `STRUCTURALLY_VALID`. The bounded envelope
calculator requires a valid convex metre parcel with an explicit CRS and a traceable
setback for every edge; complex, incomplete, stale or conflicting inputs fail closed.
See `LOCAL_RULE_PROJECT_CODE_BASIS.md` and the associated ADR. No real municipal source
is qualified by these contracts and no runtime or Generator consumer is activated.

## Generation and validation design

Input schema requires location/evidence, valid metre plot, access edges, north, source-bound authority/envelope, confirmed unit program, identical floor IDs, reservations, explicit seed/budget/strategy and weights. Preflight verifies structure, closed simple polygons, positive area, containment, access-edge references, unique reservations and unit totals. It still returns REVIEW_REQUIRED because legal authority and project signatures are not independently qualified.

Generation strategy is bounded enumeration of core alternatives, then unit partitions, room adjacency/topology, door/window hosts, furniture operating/usage envelopes and vertical reservations. Candidate identity must hash semantic input, exact rules, algorithm, seed and geometry. No source plan is a hidden template. Complete independent hard validation precedes ranking. A failed, missing or skipped hard check blocks, including an extra declared failed check. All metrics must be finite0–1 and weights finite nonnegative with positive sum; ties sort by stable candidate ID.

Metrics require versioned definitions/calibration: net usable/enclosed ratio for efficiency; qualifying exposed habitable area for daylight; visible entrance-to-private openings for privacy; required furniture and usable clearances for usability; wet adjacency and verified shaft path for service efficiency; exact reserved-geometry compatibility for MEP/structure. Marketability and overall design quality require owner or human evidence, not AI-invented scores. Numeric calibration is not supplied by the122-plan study.

NO_FEASIBLE_LAYOUT requires exhaustive finite/certified proof with binding constraints. Budget exhaustion is REVIEW_REQUIRED; missing authority INPUT_REQUIRED; unresolved contradictory authority CONFLICT. Owner-controlled relaxation proposals must be explicitly tested and never relax a legal rule. No infeasibility solver is implemented in this release.

Architecture→MEP handoff must preserve room/use/level IDs, exact polygons, openings, fixed shafts and vertical groups, wet fixture roles, equipment footprints and service access. It reserves space without choosing capacities, pipe sizes, routes, loads or connection coordinates. Missing shaft/port evidence remains INPUT_REQUIRED.

## Gap closure, local authority and ergonomics

`research-completion.json` assigns exactly one result to each of the24 gaps. Site, envelope, shaft, MEP and structural items require project evidence. Urban and parking items use a local-rule interface keyed by city, jurisdiction, parcel, instruction date, source hash and reviewer; absent local data returns INPUT_REQUIRED and no Tehran or national default is supplied. Dining, master-bedroom, laundry and storage program choices remain owner inputs. Fire, elevator, acoustic, accessibility and security clause coverage remains source work, not inferred rules.

The ergonomic model distinguishes OBJECT_FOOTPRINT, USAGE_CLEARANCE, ACCESS_CLEARANCE, MAINTENANCE_CLEARANCE and CODE_REQUIRED_CLEARANCE for15 essential object groups. It records the evidence hierarchy but deliberately supplies no invented clearance values. A missing envelope returns FIT_INPUT_REQUIRED. The41 original symbols therefore remain a useful geometry foundation but are insufficient for V1 fit validation.

## Golden, performance and delivery

**HUMAN_ARCHITECTURE_GOLDEN_REQUIRED**: approved owner programs, authoritative site constraints, acceptable layouts, rejected layouts and reasoned architect decisions are absent. `golden-review-template.json` supplies an empty independent-review form and eight required case types; it is not Golden truth. Synthetic unit tests do not replace human cases. Production and staging deployment are not recommended. An offline architect review packet is useful now.

No network/LLM call occurs in validation, symbols or ranking. Search budget/cache/cancellation policy is defined for future work. Cache key must include all source/rule/program/reservation/build hashes, not just plot size. Current catalog reads are bounded by small local JSON; repeated parsing can be cached only by content identity in a future profile. No current-engine throughput claims.

Reproduce: install repository requirements, run `python -m pytest tests/test_residential_foundation.py`, then `python tools/residential_foundation_report.py --output <outside-repo-directory>`. Every exported file carries automatic build identity (SVG metadata, JSON envelope, HTML audit). The browser tool rejected local-file navigation; browser rendering is unverified. No workaround server or external upload was used.
