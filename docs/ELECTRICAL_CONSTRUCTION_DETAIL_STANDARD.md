# Electrical Construction Detail Standard

## Purpose

Electrical release quality is not satisfied by a readable/reopenable DXF alone. A construction-detail sheet must contain executable geometry, traceable project evidence, and plan-to-detail references. Missing project facts remain `INPUT_REQUIRED` or `PRELIMINARY`; approved reference drawings may teach recurring drawing patterns but may not silently become project facts.

## Reference policy

Approved external project drawings may be used to learn:

- drawing-family taxonomy and sheet organization;
- recurring symbol/circuit/detail conventions;
- expected graphical depth and detail density;
- common relationships among plans, panels, risers, schedules and details.

They may **not** establish project-specific service capacity, appliance loads, fire-alarm topology, manufacturer data, mounting heights, short-circuit level, conduit sizing, local authority requirements or any other fact that is not evidenced for the active project.

For regression work, the same-project approved drawing may be held out from generation and used only after output generation for scoring. This prevents hidden copying from being mistaken for generalization.

## Eight-step construction-quality contract

1. **Reference decomposition** — decompose approved references into sheet families, detail families, symbols, topology and graphical-density characteristics without promoting project-specific values.
2. **Dimension engine** — required dimensions/clearances are represented as real drawing information. Unknown values are labeled as project/local-rule inputs instead of fabricated numbers.
3. **Installation material model** — construction details represent relevant host/material/connection concepts such as wall/slab, enclosure, conduit/cable, sleeve/firestop, terminal/lug, PE/N bars, clamp and earth connection when applicable.
4. **Plan-to-detail linking** — applicable plan sheets reference generated detail IDs. Orphan detail references and missing owners fail closed.
5. **Panel execution content** — schedules expose load/current/protection/cable/evidence state and do not hide unresolved project fields.
6. **Fire and low-current details** — required fire/ELV systems receive their own installation/topology/termination details rather than relying on a generic low-current note.
7. **Evidence consistency** — `FINAL` values require a real value and allowed source; objects with missing inputs cannot be `FINAL`.
8. **Construction Detail Gate** — text-heavy or geometrically sparse placeholder details fail even when the DXF audit/reopen succeeds.

## Machine gates

The active acceptance pipeline includes:

- `EVIDENCE_CONSISTENCY_AUTHORITY`
- `PLAN_DETAIL_LINK_AUTHORITY`
- `CONSTRUCTION_DETAIL_AUTHORITY`
- existing plan isolation, semantic duplicate, same-file reopen, safe-area and visual QA gates.

A failed or incomplete mandatory gate prevents production acceptance. A numerical execution score never overrides a hard blocker.

## Structural detail gate

The construction gate uses structural checks rather than universal engineering numbers. It checks that:

- required detail layouts exist;
- generated detail IDs are rendered;
- detail sheets contain a minimum amount of real graphic geometry relative to the number of generated details;
- output is not dominated by text in place of construction geometry;
- required detail parameters are supplied before construction acceptance;
- plan/detail references resolve to real generated details.

These thresholds are QA heuristics for detecting placeholder output. They are not electrical design rules and do not set project mounting heights, cable sizes, breaker ratings or other engineering values.

## Release rule

`PASS` means the generated artifact satisfies the machine construction-detail contract for the evidence supplied. It does **not** mean approval by an authority or permission to construct. Project-specific utility, fire-authority, manufacturer, installation-method and professional-review inputs remain required where identified by the project evidence model.
