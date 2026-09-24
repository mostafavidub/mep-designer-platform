# Semantic Dimension Reference Benchmark

**Status:** Engineering benchmark evidence  
**Rule:** `MEP-DIM-001`  
**Scope:** Mechanical-plan dimensioning and the shared semantic dimension foundation  
**Privacy:** Reference projects are anonymized. Their dimensions are comparison evidence only and are never hidden design defaults.

## 1. Corpus

Six independent architectural DXF projects were inspected entity-by-entity.

| Metric | Result |
|---|---:|
| DIMENSION entities | 835 |
| Linear/rotated | 810 (97.01%) |
| Aligned | 25 (2.99%) |
| Numeric text overrides | 16 (1.92%) |
| Non-numeric overrides | 18 (2.16%) |
| Zero-measurement dimensions | 7 (0.84%) |
| Distinct dominant dimension styles | `home` 807, `DB` 18, `ISO-25` 5, `ARCH2` 5 |
| Multi-dimension baseline groups | 187 |
| Chain-like baseline groups | 132 |
| Largest observed chain | 9 dimensions |

All six sources declare `$INSUNITS=4` (millimetres), while their dimension measurements are metre-like. The existing Planha unit-sanity contract resolves all six to `effective_scale_to_m=1.0` with high-confidence dimension-plausibility evidence. Therefore DXF header units are evidence, never sole authority.

## 2. Stable architectural logic observed

The corpus consistently supports the following hierarchy:

`Property/Site -> Building Envelope -> Structural Grid -> Major Internal Geometry -> Local Construction Geometry -> Critical Clearances`

The dominant pattern is not “dimension every visible distance.” It is a structured dimension network that allows construction geometry to be recovered from stable datums, with intentional overall/control dimensions.

Observed professional behavior includes:

- face-to-face Building Overall dimensions kept conceptually separate from centerline Grid chains;
- repeated adjacent chain dimensions, often grouped on common baselines;
- internal wall/set-out dimensions only where geometry must be located;
- local stair/core/shaft dimensions;
- small but construction-critical clearances;
- linear dimensions aligned to the local building axes, with aligned dimensions reserved for genuinely oblique geometry;
- multiple drawing purposes with different dimension density;
- occasional nominal/display overrides that cannot be accepted as calculation truth without corroboration.

## 3. Why layer/style cannot be authority

The same engineering role appears on unrelated layers such as `FON`, `Dime-Arch`, `EL2`, `BREAK`, `Dor`, `D-FON-2`, `DAM--FOND`, `DIM`, `Frame`, and others.

Dimension style is similarly non-semantic. The corpus is dominated by `home`, but DB/ISO-25/ARCH2 also occur.

Planha therefore uses entity geometry + semantic references + drawing purpose + provenance. Layer/style remain evidence only.

## 4. Source text is not numeric authority

The benchmark includes:

- conventional numeric nominalization/rounding such as ~2.9766 displayed as 3.00;
- repeated project-specific nominal values;
- non-numeric strings such as `20-30` and `10-15`;
- a material anomaly of geometry ~5.95 displayed as 7.00;
- seven zero-measurement source dimensions.

Planha stores geometric measurement, source displayed text, override class, canonical unit evidence and generated engineering value independently. Critical unresolved conflicts block a final-issue claim rather than being silently resolved from the displayed text.

## 5. Chain evidence

Among 461 axis/baseline groups, 187 contain multiple dimensions and 132 exhibit adjacent chain behavior. About 70.6% of multi-dimension baseline groups are chain-like.

This supports the design principle:

**Dimension Network = Minimal Set-out Graph + Intentional Check Dimensions**

It does not support independent nearest-line dimensioning or blanket room-length/room-width labeling.

## 6. Mechanical profile contract

A Mechanical plan must not duplicate the architectural dimension set wholesale.

It retains/regenerates only architectural context needed to interpret the Mechanical work and adds set-out dimensions for construction-critical Mechanical objects whose position is otherwise ambiguous.

Preferred datums:

1. proven structural Grid axis;
2. stable architectural host/face;
3. other governed stable references.

Furniture, transient annotations and unproven geometry are not Mechanical datums.

## 7. Benchmark-hardening changes

The benchmark exposed five implementation defects that are corrected by SWCIS-2026-0281:

1. **Blind raw source-dimension carry-through** — source dimensions are now preserved in the registry and selectively regenerated; the raw graphical entity is not copied blindly into Mechanical boards.
2. **Live-source contamination across generated boards** — source entities are frozen before composition.
3. **Missing context when source dimensions are absent** — proven Building Overall, consecutive Grid, Shaft and Stair/Core context can be generated from semantic references.
4. **Partial Grid chains** — completion is pair-based; existing reference pairs remain and only missing adjacent pairs are generated.
5. **Annotation-only collision handling** — placement now receives architectural/mechanical text, block, arc and circle obstacles from the actual target board.
6. **Rotated envelope support** — Overall context follows detected local building axes rather than assuming world X/Y.
7. **No-source-dimension unit ambiguity** — a unique plausible unit basis is required; ambiguity fails closed.
8. **Generated-output re-ingestion** — Planha-owned dimensions are excluded from future source registries.

## 8. Alignment assessment

| Capability | Reference logic | Planha after hardening |
|---|---|---|
| Unit plausibility | drawing behavior overrides bad metadata | Aligned |
| Linear/local-axis dimensions | dominant | Aligned |
| Aligned/oblique dimensions | limited, geometry-driven | Aligned |
| Grid vs Overall datum separation | explicit | Aligned |
| Source override preservation | mixed consultant behavior | Stricter, fail-closed |
| Source knowledge preservation | required | Aligned |
| View-specific suppression | implicit in drawing purpose | Aligned |
| Mechanical set-out | stable construction datums | Aligned |
| Adjacent Grid chains | common | Aligned for proven axes |
| Partial-chain completion | common need | Aligned |
| Shaft/Core local sizing | common | Aligned when semantic geometry is proven |
| Rotated building context | geometry-driven | Aligned for proven envelope faces |
| Collision-aware dimension text | visually coordinated | Improved; text/symbol obstacles enforced |
| Full architectural partition graph | rich and project-specific | Not yet complete |
| Intentional closure/check graph | present in professional drawings | Partial |
| Finish/core face semantics | discipline-specific | Still coarse |
| Full dimension-line/extension-line clash avoidance | visually resolved | Not yet complete |

## 9. Remaining limitations

These are intentional boundaries, not hidden PASS conditions:

- Full autonomous Architectural dimension-chain synthesis is not complete. Partition, door/window position, stair-flight, site/setback and room-clear dimension networks belong to the Architecture discipline phase and must extend this same engine.
- Wall references are still coarser than the future `INNER_FACE / OUTER_FACE / CORE_FACE / FINISH_FACE` model.
- Automatic CHECK/closure dimensions are not yet generated by a general graph-closure solver.
- Grid recognition upstream is not yet a dedicated multi-evidence Architecture contract; weak layer evidence must never become a design calculation authority.
- Placement checks dimension-text/symbol collision; full dimension-line and extension-line path clash avoidance still needs a dedicated presentation solver.
- Target-specific datum policy can be improved: wall-hosted equipment should prefer a proven host face when that is more constructible than a remote Grid.
- Critical numeric consultant overrides remain deliberately conservative and may require a human checkpoint until independent geometry/chain evidence resolves them.

## 10. Mechanical readiness conclusion

For the current Mechanical phase, the dimension model is suitable only when all of the following are true:

- units are proven;
- source critical dimensions are preserved or explicitly reviewed;
- construction-critical Mechanical targets have a complete stable-datum set-out path;
- required context dimensions are present or generated from proven geometry;
- no unresolved critical source conflict exists;
- exact-file dimension identity and canonical value traceability pass;
- collision and architecture-preservation gates pass.

Passing `DIMENSION > 0` is never sufficient.

The Architecture phase must build on `MEP-DIM-001`; it must not create a separate incompatible dimension engine.
