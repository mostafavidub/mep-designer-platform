# EngiTools Electrical v19 — Execution Standard

## Purpose
This document is the release source-of-truth for the Electrical companion, public workflow, user panel and CAD authority pipeline. It adapts discipline-independent lessons from Mechanical v19 while preserving Electrical-specific engineering logic.

## Non-negotiable evidence rule
No important engineering value may become FINAL because it is convenient, typical, or present as a UI default. FINAL values require one of: architectural evidence, explicit project design basis, engineering calculation from evidenced inputs, applicable rule with verified source/edition, manufacturer data, or explicit user input.

Architecture-derived estimates (including inferred connected load and representative route length) remain PRELIMINARY and may not be used as final sizing inputs.

## 1. Architecture and project understanding
Required capabilities:
- secure DXF/ZIP intake and resumable upload/recovery;
- units sanity and architecture reconstruction;
- print-frame classification and primary-plan isolation;
- level/room/door/window/stair/shaft/elevator/parking evidence;
- exclusion of furniture/lintel/section/elevation/duplicate frames from electrical plan generation;
- no cross-frame physical routing;
- north inherited only from actual architectural compass evidence.

Release gates: ARCHITECTURE_MODEL, PROJECT_MODEL, SYSTEM_REQUIREMENTS, PLAN_ISOLATION_AUTHORITY.

## 2. Electrical Design Basis and questions
The Electrical preflight asks only unresolved project facts. Required canonical questions are:
1. city/jurisdiction;
2. supply configuration and evidenced nominal voltage where known;
3. earthing/bonding basis;
4. service/meter/main-panel location or explicit permission to propose it;
5. dedicated-load schedule with manufacturer/nameplate data where applicable;
6. fire-alarm scope;
7. low-current scope;
8. lighting design basis;
9. project/local electrical code and confirmed edition/rule package;
10. ceiling/mounting constraints.

Question behavior:
- valid answers persist across reload/retry;
- canonicalization is idempotent;
- late CAD INPUT_REQUIRED errors reopen only the exact missing question(s);
- prior architecture analysis and answered questions remain preserved;
- generic failure pages are not used for resolvable missing design-basis inputs.

## 3. Standards and rule governance
Verified standards families may provide applicable-rule evidence, never project facts. The registry currently tracks:
- IEC 60364-1:2025;
- IEC 60364-5-53:2019 + AMD1:2020 + AMD2:2024 consolidated edition;
- IEC 61439-1:2020;
- IEC 62305 Parts 1–4:2024 where lightning protection is applicable.

Project/jurisdiction inputs remain required for:
- applicable edition/package of Iran National Building Regulations, Topic 13;
- local utility/service/metering requirements;
- local fire-authority requirements.

The rule registry must not contain hard-coded breaker sizes, cable sizes, mounting heights, service capacity, fixture counts or other project facts.

## 4. System-scope resolver
Electrical scope is project-driven. Lighting and power are resolved per eligible floor; dedicated power, HVAC power, elevator/pump power, emergency systems, fire alarm, low current, grounding/bonding, lightning protection, generator, UPS, EV and PV are included only when evidence/answers make them applicable. Optional systems that are NOT_REQUIRED must not leak into sheets, legend, calculations or schedules.

## 5. Project-driven drawing-set review
No global fixed sheet count is permitted. The manifest is generated from levels and applicable systems. Base families include cover/index, general notes, per-level lighting, per-level power, panel schedules, single line, grounding, calculations and details; riser is conditional on vertical distribution; fire-alarm and low-current plans are conditional.

Public workflow:
- user sees exact sheet list and count;
- user explicitly approves the delivery manifest;
- approved manifest is persisted with SHA-256;
- design cannot silently approve or mutate the public manifest;
- authenticated panel workflow may persist its reviewed/authorized manifest before queueing.

## 6. Lighting and equipment placement
Lighting quantities require a valid design basis plus manufacturer/fixture data where calculation needs them. Placement is host-aware and room-aware. Switches must satisfy door/entry relationship when final. Equipment representation must include real block, tag and host/room traceability. No PRELIMINARY placement may masquerade as final.

## 7. Power, topology and routing
Loads are traceable equipment -> load -> branch circuit -> panel -> feeder -> main -> meter -> service. Circuit grouping, phase assignment, panel ownership and physical routes must remain deterministic and plan-aware. Physical cross-frame connections are prohibited; vertical connectivity is expressed through riser/service topology.

## 8. Engineering calculations
Final load, current, cable, protection, voltage drop, phase balance, panel main/bus/spares and feeder values require evidenced inputs and calculation provenance. Architecture proxies do not satisfy these inputs. Cable/protection tables and manufacturer data must be explicitly supplied/installed with source reference before final sizing.

Release gates include CIRCUIT_TOPOLOGY, LOAD_CALCULATION, CABLE_SIZING, BREAKER_SIZING, VOLTAGE_DROP, PHASE_BALANCE, PANEL_DESIGN and PANEL_SCHEDULE.

## 9. Service, SLD, riser, grounding and optional systems
- service entry, meter and main distribution must be traceable;
- SLD must reflect the same topology as plans/schedules;
- riser is project-driven and each transition has feeder/protection/tag evidence;
- grounding/bonding is generated only from project evidence/rules;
- fire alarm and low current fail closed if REQUIRED but under-specified;
- NOT_REQUIRED optional systems produce no phantom drawings/content.

## 10. Details, legend and documentation
Detail requirements are resolved from actual systems/equipment. Required detail IDs, inserted detail IDs and plan references must match exactly. No orphan details or references. Legend is used-symbol-only. General notes distinguish FINAL facts from INPUT_REQUIRED/PRELIMINARY items.

## 11. Drawing composition and preservation
Each sheet owns independent Paper Space geometry. The architecture underlay is preserved conservatively. Cleanup is preservation-first: architecture is never deleted by geometric region alone. Electrical content must remain in the safe drawing area and never overlap the title band. North is drawn only from architectural compass evidence.

## 12. Review, revision and recovery
The Electrical companion and user panel use the same hardened runtime concepts as Mechanical:
- durable project/revision state;
- persistent answers and analysis;
- approved manifest hash;
- resumable design/retry without duplicate work;
- exact INPUT_REQUIRED recovery;
- progress/error states suitable for users rather than raw stack traces;
- artifact identity and downloadable final file tied to the revision;
- stale analyzer refresh only when version evidence requires it.

## 13. CAD/runtime identity
The web service routes Electrical jobs only to `/design-electrical-v19`. A successful CAD response must identify:
- mode = `electrical-v19-authoritative`;
- pipeline_authority = `electrical-v19`.

CAD and site/UI release contracts are deliberately separate because the CAD Docker image contains only `cad_engine`. `/system_health` must report both contracts and composite Electrical v19 health.

## 14. QA and final-file rule
Final acceptance is performed on the exact delivered file:
GENERATE -> SAVE -> CLOSE -> REOPEN SAME FILE -> VALIDATE -> RENDER SAME FILE -> VISUAL INSPECTION -> DELIVER.

Required checks include:
- sheet content signatures;
- family purity;
- same-family semantic duplicate detection;
- safe drawing area;
- reference-behavior similarity;
- visual QA;
- exact layout/manifest match;
- DXF audit;
- final reopen authority QA.

A synthetic PASS never authorizes production release. A real raw DXF/ZIP plus its SHA is required for real-project release.

## 15. Execution-readiness score
100-point model:
- architecture/scope: 15;
- design basis: 15;
- engineering calculations: 20;
- drawing coverage/traceability: 15;
- visual/documentation: 10;
- same-file reopen/semantic QA: 10;
- panel flow/recovery: 10;
- runtime/release identity: 5.

Execution-review-ready requires BOTH:
- score >= 80;
- zero mandatory hard blockers.

Mandatory blockers include NO_FAKE_FINAL, ARCHITECTURE_MODEL, DESIGN_BASIS, CIRCUIT_TOPOLOGY, FINAL_FILE_REOPEN, FINAL_REOPEN_AUTHORITY, PANEL_FLOW_RECOVERY and RUNTIME_RELEASE_IDENTITY. A high numerical score can never waive one of these gates.

## 16. Release checklist
Do not merge/deploy until:
- Electrical dedicated CI PASS;
- relevant shared regressions are green or proven no worse than base;
- site and CAD release contracts PASS;
- panel question/reload/retry/recovery tests PASS;
- real raw project acceptance has been executed;
- reference similarity PASS on that real output;
- actual visual inspection PASS on that same output;
- same-file reopen PASS;
- execution score >=80 with no hard blockers;
- fail-closed production release evaluator permits release;
- post-deploy live upload -> questions -> manifest review -> design -> download -> reopen validation passes.

Even after these automated gates, produced construction documents remain subject to the required professional/authority review for the project jurisdiction.
