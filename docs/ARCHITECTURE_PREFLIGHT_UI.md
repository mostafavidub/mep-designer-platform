# Planha Architecture Preflight UI

## Scope

Architecture Preflight UI is an experimental Persian RTL presentation and transport layer over the qualified backend Review Engine. It displays backend state, bounded questions, exact allowed answers, evidence, impact, preview requests, source-correction guidance, revalidation results, and server-created snapshot identity. It contains no architecture recognition or engineering qualification logic.

## Integration

The canonical application registers `app/architecture_preflight_ui.py` from `app/main_health.py`. The dedicated routes are separate from ordinary project/design questions:

- `GET /projects/{pid}/architecture-preflight`
- `GET /projects/{pid}/architecture-preflight/state`
- `POST /projects/{pid}/architecture-preflight/review/{review_item_id}`

Every route resolves the signed-session user and project owner before reading preflight state. Foreign or missing projects return the same `404`. The existing generic questionnaire, `Project.status`, `Project.questions`, and `Project.answers` remain unchanged.

The additive experimental state is stored under `Project.analysis["architecture_preflight_ui"]`. This avoids browser-only state, process memory, and database migration. The namespace contains one current canonical candidate plus the compact registry, current snapshot and request-id records. JSON is copied, replaced and committed atomically. The review POST locks and re-resolves the owned project row before recomputing the authoritative current plan.

## View model

The server view model translates state, impact, evidence keys and answer enums into concise Persian presentation. Enum values remain unchanged for transport. It cannot add/remove answers, change reviewability, select engineering state, construct snapshots, or infer facts from geometry.

The four primary views are:

- `AUTO_VALIDATED`: states that current engine-required architecture input passed its validation gate; it does not claim a perfect drawing or licensed approval.
- `QUICK_REVIEW_REQUIRED`: shows the first backend-ordered item, progress from the registry, exact answers, evidence and advisory recommendation.
- `ARCHITECTURE_INPUT_REQUIRED`: contains no answer controls and explains where evidence is missing, why it matters and what source correction is required.
- `CONFLICT`: blocks submission and distinguishes authoritative conflict from an internal engine/contract defect.

## Safe decision transport

The browser sends exactly `review_item_id`, `decision`, `review_fingerprint`, and `request_id`. Unknown fields are rejected. The server verifies CSRF, ownership, project binding, current item, current fingerprint and the current backend `allowed_answers`, then constructs the complete replay payload from the authoritative item. The browser cannot submit source identity, canonical models, geometry, authority, effects, answer lists, validator state, or snapshots.

Request IDs are bound to a deterministic payload hash. Same-key/same-payload retry returns the current result without duplicate authority; same-key/different-payload is rejected. Stale items return `409`, invalid answers/payloads return `422`, and foreign projects return `404` without enumeration.

After an accepted decision, the backend Review Engine applies its allowlisted overlay, independently revalidates the candidate, derives the next plan, and creates a snapshot only from `PASS`. Frontend JavaScript never simulates validation.

## Viewer and source safety

The backend crop contract is used exactly. The server selects only explicitly related existing canonical entities and converts them to bounded finite numeric primitives. The browser creates SVG nodes with `createElementNS` and text nodes with `textContent`; it never embeds raw source SVG/HTML, file paths, external resources, scripts, event attributes, `foreignObject`, OCR or pixel inference.

Pan, zoom, fit and reset change only the SVG `viewBox`. There are no handles or commands for Walls, apertures, Portals, Voids, polygons, dimensions or Access edges. Layer visibility and rendering cannot alter architecture state.

## Accessibility and responsive behavior

The page is Persian RTL. IDs, hashes, technical codes and coordinates use LTR spans. Answers use radio controls inside a fieldset, all controls are keyboard accessible, focus is visible, submission status uses `aria-live`, and states use text/icons in addition to color. Desktop uses a drawing-first two-column layout; view and review stack below 900 px.

## Persistence and lifecycle

Returning to the page reconstructs the current plan from the server-side canonical model and review registry. Accepted answers are not browser history. A source or model identity mismatch blocks the page as stale. A reviewed Snapshot remains server-produced and is displayed without client-side identity calculation.

## Security controls

- signed-session owner binding on GET and POST;
- per-session CSRF token for review POST;
- row-level owned-project query before mutation;
- strict JSON payload allowlist;
- backend answer and fingerprint validation;
- idempotency key collision protection;
- Jinja autoescape and DOM-only safe SVG primitives;
- no path/source-reference input from the browser;
- customer-safe errors with no stack trace.

## Fasihi development diagnostic

For Ground `FRAME-C7C5B4F856993D8A`, the known source-insufficient Toilet access is shown as `ARCHITECTURE_INPUT_REQUIRED`. The page explains that a Door-like motif does not provide a source-backed wall aperture. It deliberately provides no “create Door” action. Symbolic Portal authority remains a separate research/qualification task.

## Production status

The integration is experimental and additive. No public production migration, database schema migration, `.planha` lifecycle, Certified DXF, plugin, Symbolic Portal, Mechanical v2 migration, Staging or Production deployment is included.
