# Architectural Vision Recovery Runtime

The canonical architecture engine is deterministic first. If its completeness
gate fails, the same project-analysis call automatically enters a bounded
multimodal recovery state machine. Golden review files are QA-only and are
never read by this runtime.

## Configuration

- `ARCH_VISION_PROVIDER=openai` selects OpenAI.
- `ARCH_VISION_PROVIDER=deepseek` selects DeepSeek through its OpenAI-compatible
  Responses API at `https://api.deepseek.com`.
- `ARCH_VISION_MODEL` is required and selects the deployed multimodal model.
- `OPENAI_API_KEY` is required by the OpenAI provider.
- `DEEPSEEK_API_KEY` is required by the DeepSeek provider. For the supported
  DeepSeek Vision route, set `ARCH_VISION_MODEL=deepseek-flash`.
- `ARCH_VISION_TIMEOUT_SECONDS` defaults to 90 seconds.
- `ARCH_VISION_MAX_RETRIES` is capped at one retry and applies only to transient
  timeout, rate-limit, connection and provider-unavailable failures.
- `ARCH_VISION_CACHE_DIR` controls render and provider-response caching.
- `ARCH_VISION_MAX_TARGETED_QUESTIONS` and
  `ARCH_VISION_MAX_QUESTION_RATIO` are operational safeguards against turning
  engine failure into a bulk user questionnaire.

Missing provider, model or credential produces an explicit configuration error.
It never silently falls back to a successful NoVision result.

Both providers use the same prompt, strict JSON Schema, pixel/CAD transform,
validation and CAD reconciliation path. Provider selection changes only the
transport configuration. Runtime code never loads Golden Truth and never sends
Mechanical reference drawings.

## Authority and repair

Vision returns pixel-space physical spaces, functional zones and portal
candidates through a strict JSON contract. Every coordinate is converted using
the render manifest's exact affine transform. Vision remains supporting
evidence until reconciliation.

The fusion layer can:

- reclassify a CAD space when polygon and semantic evidence agree;
- merge CAD cells only when their union agrees with Vision and no accepted CAD
  wall supports the shared boundary;
- propose door, window and open-passage candidates only near an accepted CAD
  wall;
- reject unsupported geometry or conflict with strong CAD evidence.

Each proposal records its before/proposed state, CAD evidence, Vision evidence,
source handles, validation outcome and stable repair identity. Enclosure and
access graphs remain separate. After repairs, adjacency, opening bindings,
coverage, dimensional reconciliation and completeness are recalculated.

## Bounded operation

At most one global render/analysis and one localized unresolved-area
render/analysis are run per authoritative frame. If material ambiguity remains,
the engine reports `AUTOMATED_RECONSTRUCTION_INSUFFICIENT`. Only a small,
non-material remainder may become `TARGETED_HUMAN_DECISION`.

## Privacy and cache invalidation

Only the floor render and bounded CAD region context are sent. No project owner data,
Golden Truth or Mechanical reference is included. Cache identity includes the
provider, source/render hash, configured model, prompt revision, schema revision,
transform revision, frame, scope and region contract. DeepSeek and OpenAI can
therefore never reuse each other's cached result.

The call log records provider, model, request ID when returned, latency, cache
status and token counts when returned. Credentials, authorization headers,
base64 images and provider exception bodies are never persisted. Cost is not
invented: it can be calculated only after the applicable provider price and
request timestamp are available.

Oversized inline images, authentication, budget/quota, rate limit, timeout,
provider outage, incomplete response, invalid JSON and schema failure all have
separate fail-closed error codes. A provider failure leaves architecture
incomplete; it cannot authorize downstream Mechanical generation.
