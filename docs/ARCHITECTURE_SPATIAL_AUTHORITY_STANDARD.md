# Architecture Spatial Authority Standard

**Contract:** `planha-canonical-architecture/3.2`

**Spatial authority:** `planha-architecture-spatial-authority/1.0`

## Purpose

Planha may use an architectural fact for engineering only when the exact source
geometry, reconstruction rule, canonical object, validation result and consumer
grant are traceable. A convincing label or preview is never a substitute for
physical geometry.

## Evidence classes

The model keeps these classes separate: exact text occurrences; DXF geometry;
source-backed separator segments; enclosed physical spaces; exterior site
spaces; internal voids; vertical circulation; hosted openings; enclosure/access
topology; and semantic hosting. Text may describe an existing object. It cannot
create a wall, polygon, site, void, shaft, stair, opening, scale, north direction
or routing obstacle.

## Authority lattice

`TEXT_ONLY`, `GEOMETRY_CANDIDATE`, `BOUNDARY_SUPPORTED`,
`PHYSICAL_SPACE_VERIFIED`, `SEMANTICALLY_HOSTED`, `TOPOLOGY_VERIFIED` and
`ENGINEERING_READY` are distinct states. Centroids and bounding boxes are
derived conveniences. They never carry geometry authority.

Every verified physical space has a valid source-coordinate polygon, valid
interior rings, source-backed boundary segments, stable provenance fingerprint,
frame/level identity and explicit geometry, semantic, topology, scale and area
status. Metric area is granted only when drawing units/scale are verified.

## Site and void relations

The property/site boundary is independent of the building envelope. Exterior
site space is the source-backed area inside a verified site boundary and outside
the verified building envelope. An internal void lies inside the envelope.
Backyard, yard, courtyard and lightwell names may refine an existing geometric
object; the label does not create that object. If the site boundary is absent or
ambiguous, exterior-site classification remains `INPUT_REQUIRED`.

## Stairs and cores

Stair assemblies keep core, flights, landings and tread/riser lines separate.
Regular repeated lines are only a candidate. Verified stair authority requires
source-backed tread lines, spacing consistency, side-boundary evidence and a
source-closed core. Missing evidence returns `INPUT_REQUIRED`; the detector does
not synthesize a core or landing.

## Openings and topology

A verified door, window or open passage requires a real host separator and
source gap evidence. The Enclosure Graph describes space-to-separator relations.
The Access Graph contains only hosted verified doors, open passages and qualified
vertical connections. A shared wall never implies access.

## Downstream gates

Each consumer declares only the facts it needs. Room-load calculations require
verified room polygons and metric area. Exterior-load calculations additionally
require site relation and enclosure topology. Routing requires room polygons,
enclosure topology and access topology. Vertical routing additionally requires
qualified vertical circulation. A missing prerequisite returns
`INPUT_REQUIRED` with the exact missing authorities; it cannot produce a precise
engineering result.

## Golden and review

Independent Golden annotation is performed from raw DXF primitives without
runtime output. Schema `architectural-topology-golden/2.0` adds site boundaries,
site spaces, stair assemblies, landings, tread/riser lines, elevators, shafts and
semantic labels. Every plan gets a separate raw preview and annotated overlay.
Private source drawings stay outside Git; source hashes, frame identities,
review state and privacy-safe semantic baselines may be versioned.

`UNKNOWN`, `INPUT_REQUIRED`, `AMBIGUOUS`, `CONFLICT` and
`HUMAN_REVIEW_REQUIRED` are successful fail-closed outcomes when source evidence
cannot support engineering authority.
