# EngiTools Electrical Project-Driven v1

## Status and release rule

This document is the implementation contract for the Electrical Engineering Drawing System. Work is isolated on `feature/electrical-project-driven-v1`. Production must not be changed until Real Project Acceptance, Reference Similarity, and Final File Re-open QA all PASS.

Engineering outputs may only be FINAL when their provenance is one of: architectural evidence, project design basis, engineering calculation, applicable rule/reference, manufacturer data, or explicit user input. Missing evidence is represented as `UNKNOWN`, `INPUT_REQUIRED`, or `PRELIMINARY`; it is never replaced by a fabricated final value.

## Phase 0 audit — current Electrical

The current electrical implementation is the v10 family (`cad_engine/main_v10.py` + v10.2 patch). It produces useful CAD structure, but it is generator-oriented rather than project-model-oriented.

Observed gaps:

- The existing electrical unit test supplies a fixed list of systems rather than deriving project requirements.
- Current placement logic uses room label points and proxy offsets for many fixtures rather than host-aware architectural contracts.
- The v10 engine contains fixed preliminary examples such as parking luminaire arrays, generic room sockets, kitchen REF/WM/DW points, generic panel tags, and preliminary breaker/cable strings.
- Presence of layouts/layers/blocks is treated as a major success criterion; this does not prove engineering traceability, circuit-to-panel consistency, load calculation, phase balance, voltage drop, reference similarity, print readability, or save-close-reopen integrity.
- The current electrical model does not expose a canonical Electrical Project Model with per-field `source`, `confidence`, and `status`.
- Drawing-set composition is not driven by content density, annotation density, system need, panel count, circuit count, or reference-family behavior.

The current v10 implementation is therefore retained only as a legacy comparison target and must not be used as the authority for final engineering values.

## Phase 0 audit — Mechanical v13/v14 architecture

Mechanical has evolved into a staged data pipeline. The reusable architectural pattern is:

`DXF -> Architectural Reconstruction -> Recognition -> Requirements -> Calculations -> Topology -> Routing -> Sizing -> Annotation -> Details/Schedules -> Sheet Composition -> QA`

The v14 runner validates observable stage outputs and reports errors/warnings instead of assuming success. Its strongest reusable concepts are architectural reconstruction, evidence tracking, system requirement resolution, topology-first design, routing separation, sizing separation, annotation separation, detail generation, independent sheet composition, and explicit QA.

Mechanical-specific engineering logic is not reusable as electrical logic. Pipe sizing, sanitary slopes, HVAC calculations, fixture semantics, gas rules, and wet-core routing remain discipline-specific.

## Shared infrastructure map

| Shared concept | Target reusable component | Electrical specialization |
|---|---|---|
| Drawing frame detection | `shared_drawing.frames` | Electrical eligibility filter |
| Drawing type classification | `shared_drawing.classifier` | Electrical-required drawing types |
| Project model base | `project_core.evidence` | ElectricalProjectModel schema |
| Sheet ownership | `shared_drawing.ownership` | prohibit cross-frame electrical geometry |
| Adaptive sheet planner | `shared_drawing.sheet_planner` | electrical family density/signatures |
| Independent geometry | `shared_drawing.composer` | family-pure electrical entities |
| Paper space/title block | `shared_drawing.paper_space` | E-series numbering/metadata |
| Content signature | `shared_qa.content_signature` | Lighting/Power/Fire/etc signatures |
| Semantic duplicate detection | `shared_qa.duplicate` | electrical family comparison |
| Visual QA | `shared_qa.visual` | electrical symbol/annotation visibility |
| Final reopen QA | `shared_qa.reopen` | electrical manifest/layout integrity |
| Legend framework | `shared_drawing.legend` | used electrical symbols only |
| Detail framework | `shared_drawing.details` | electrical parametric details |
| Reference similarity | `shared_qa.reference_similarity` | electrical family dimensions |

## Approved Electrical reference audit

The analyzed approved reference set establishes behavior, not universal code values. Project-01 electrical contains 59 layers and 19,460 modelspace entities. Observed electrical families include LIGHT/EL/EL2, E-FIRE/E-FIRE ALARM, E-bonding/Hambandi, E-WIRE, E-INSTRU and E-SOUND.

Reference rules used by the target architecture:

1. Lighting and power are separable drawing families; they are not collapsed into one crowded plan.
2. Lighting is not symbol-only: control/circuit graphics and engineering annotation are present.
3. Switch placement is tied to room entry/door geometry.
4. Receptacles are room-use-aware; dedicated loads are distinct from general outlets.
5. Every electrical load must be traceable through a circuit to a panel.
6. Panel location and distribution are explicit and accessible.
7. Wet areas and kitchens require coordinated, equipment-aware electrical decisions.
8. Similar/typical architectural floors are still individually validated.
9. Electrical feeds for mechanical equipment are cross-checked with mechanical equipment.
10. Fire alarm, when required, is a traceable independent system with panel/devices/routes/annotations.
11. Approved drawings do not establish universal final cable sizes, breaker sizes, installation heights, fire spacing, or other regulatory constants. Those remain project inputs/rules/calculations.

## Gap analysis against requested phases

### Architecture and project understanding

Current: partial room/level extraction and proxy special plans.
Target: levels, rooms, polygons, walls, doors, windows, stairs, shafts, parking, roof, service spaces, entrances, wet spaces, kitchens, bedrooms, living/common/outdoor areas, footprint, unit boundaries when detectable, plus classified print frames and per-field provenance.

### Design basis and requirement resolution

Current: fixed systems can be passed by caller and assumptions are embedded in generator logic.
Target: explicit Design Basis values with source/confidence/status; evidence-based System Requirement Resolver with REQUIRED / NOT_REQUIRED / INPUT_REQUIRED / PRELIMINARY decisions.

### Equipment and placement

Current: many symbol points derive from room label points or fixed offsets.
Target: Placement Contracts with host type, door/window conflict, room ownership, clearances, orientation, and host-distance QA. Mechanical v14.4 wall-hosting is the geometric precedent, not a code copy.

### Engineering model

Current: drawings can contain circuit-like routes but there is no complete canonical load->branch circuit->panel->feeder->main->service graph.
Target: first-class topology entities with no orphan loads/circuits and bidirectional schedule/plan/SLD traceability.

### Calculations and sizing

Current: preliminary breaker/cable labels appear in generator code.
Target: connected/demand/diversified/panel/phase/feeder/service calculations with provenance; cable and breaker sizing only when design basis/rule tables are sufficient; otherwise INPUT_REQUIRED/PRELIMINARY.

### Drawing set and presentation

Current: static layout expectations dominate tests.
Target: adaptive manifest driven by systems, levels, density, panel/circuit/equipment count, annotation density, print readability and reference patterns; independent sheet geometry and paper space.

### QA and release

Current: file audit, layout/layer/block existence and orthogonal route checks exist.
Target: architecture gate, model gate, design-basis gate, system gate, placement, topology, calculations, sizing, voltage drop, phase balance, panel/schedule/SLD/riser synchronization, family purity, content signature, semantic duplicate, reference similarity, visual render, and save-close-reopen validation.

## Target architecture

```text
ElectricalPipeline
├── 00 Ingest / ArchitecturalUnderstanding
│   ├── DXF/ZIP resolver
│   ├── frame detector + classifier
│   ├── architectural semantic extractor
│   └── ArchitectureGate
├── 01 ElectricalProjectModel
│   ├── EvidenceValue<T>
│   ├── project/levels/units/rooms/zones
│   └── ProjectModelGate
├── 02 ElectricalDesignBasis
│   ├── explicit inputs
│   ├── rule/reference inputs
│   └── missing-input registry
├── 03 SystemRequirementResolver
├── 04 ReferenceTaxonomy
├── 05 AdaptiveElectricalSheetPlanner
├── 06 EquipmentRequirementResolver
├── 07 CADSymbolLibrary + PlacementContracts
├── 08 LightingDesignEngine
├── 09 PowerReceptacleEngine
├── 10 CircuitTopologyEngine
├── 11 RoutingEngine
├── 12 LoadCalculationEngine
├── 13 CableBreakerSizing + VD/PhaseBalance
├── 14 Panelboard + PanelSchedule
├── 15 SLD + Riser
├── 16 Grounding/Bonding
├── 17 FireAlarm/LowCurrent optional engines
├── 18 EquipmentRepresentation + Annotation
├── 19 DetailResolver + ParametricDetailLibrary
├── 20 PlanDetailLinker + ProjectLegend + GeneralNotes
├── 21 IndependentSheetComposer + PaperSpace
└── 22 AcceptanceQA
    ├── content signatures / family purity
    ├── semantic duplicate
    ├── reference similarity
    ├── visual QA
    └── final file reopen
```

The public pipeline maps these implementation components to the requested Phase 0–37 gates; the implementation is modular rather than creating 38 unrelated files.

## Migration plan

1. Freeze legacy electrical v10 as comparison-only; add tests demonstrating its hard-coded/proxy limitations.
2. Introduce common evidence/status types and Electrical Project Model without changing production routes.
3. Introduce architecture/frame classification and Architecture Gate.
4. Introduce Design Basis and System Requirement Resolver.
5. Encode approved reference taxonomy as evidence descriptors, never as universal engineering constants.
6. Introduce adaptive sheet manifest and per-family content signatures.
7. Implement room-aware equipment requirements, standard electrical blocks and host-aware placement contracts.
8. Implement lighting and power design models; keep unknown manufacturer/code inputs preliminary.
9. Implement canonical circuit topology and architecture-aware same-sheet routing.
10. Implement load calculations, cable/breaker sizing contracts, voltage-drop and phase-balance gates.
11. Implement panels, schedules, SLD and risers from the same topology graph.
12. Implement grounding and optional fire/ELV engines under requirement gates.
13. Implement annotations, detail resolver/library, plan-detail links, project legend and project notes.
14. Implement independent sheet composer/paper space and family-purity/duplicate checks.
15. Implement reference-similarity scoring and render-based visual QA.
16. Implement save-close-reopen validation against manifest and content signatures.
17. Run unit tests, integration tests and synthetic real-project fixtures on branch.
18. Run the actual reference/real architecture project and compare each family.
19. Only after all acceptance gates pass, review a production migration separately. No production deployment is part of this branch until then.

## Test matrix

| Gate | Unit test | Integration test | Real-project assertion |
|---|---|---|---|
| Architecture Model | room/frame classifiers | DXF -> semantic model | expected levels/frames/rooms, no cross-frame geometry |
| Project Model | provenance/status invariants | architecture -> EPM | no fabricated FINAL fields |
| Design Basis | missing input semantics | basis merge | unknown values remain INPUT_REQUIRED |
| System Requirements | evidence rules | project+basis -> systems | no unrelated systems |
| Reference Taxonomy | family parser | reference -> taxonomy | approved families represented |
| Sheet Manifest | merge/split rules | systems+levels+density | dynamic count, correct ownership |
| Equipment Requirements | room rules | rooms -> requirement set | room-use consistency |
| Equipment Placement | host/door/window tests | requirements -> placements | host distance/orientation/collision PASS |
| Lighting Design | area/lux contract | rooms -> fixtures | no final lux count without luminaire data |
| Power Design | load contracts | equipment -> loads | dedicated/general separation |
| Circuit Topology | graph invariants | load -> circuit -> panel | zero orphan loads/circuits |
| Routing | same-frame path | topology -> routes | no giant cross-frame lines |
| Load Calculation | arithmetic/provenance | topology -> loads | panel/service totals reconcile |
| Cable/Breaker | rule-table boundary | circuits -> sizing | no random final sizes |
| Voltage Drop | formula/path length | routes+sizing | required circuits within configured criterion |
| Phase Balance | phase allocation | panels -> balance | threshold gate enforced |
| Panel Design | panel schema | topology -> panels | all circuits assigned |
| Panel Schedule | 1:1 sync | panels -> schedules | plan/schedule exact match |
| SLD | graph projection | topology -> SLD | tags match panels/feeders |
| Riser | level transitions | topology -> riser | no physical cross-sheet vertical line |
| Grounding | evidence/status | project -> grounding | missing soil/utility data not invented |
| Fire/ELV | optional requirement | requirement -> family | absent systems generate no entities/legend |
| Representation | block contract | equipment -> CAD | symbols visible and tagged |
| Annotation | collision/readability | routes -> labels | no overlaps at print scale |
| Details | resolver rules | equipment/system -> details | no orphan detail/reference |
| Legend/Notes | used-symbol filter | project -> docs | only used symbols/project notes |
| Sheet Signature | family signatures | composed files | no underlay-only sheets |
| Family Purity | layer policy | composed files | forbidden layers absent |
| Semantic Duplicate | fingerprint | drawing set | distinct-purpose duplicates fail |
| Paper Space | layout metadata | manifest -> layouts | layout count/title/scale match |
| Reference Similarity | metric scorer | render+semantics | threshold by family |
| Visual QA | visibility/collision | render pipeline | readable symbols/text/routes |
| Final Re-open | serialization invariant | save/close/reopen/render | same file, same manifest/signatures |

## Acceptance state machine

`DRAFT -> PRELIMINARY -> VALIDATED -> ACCEPTED`

`ACCEPTED` is only reachable when every applicable acceptance gate reports PASS. A required gate in FAIL blocks release. An INPUT_REQUIRED engineering field cannot be silently promoted to FINAL. Non-applicable optional systems are recorded as NOT_REQUIRED rather than being falsely passed.
