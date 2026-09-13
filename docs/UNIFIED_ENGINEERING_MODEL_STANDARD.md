# Unified Engineering Model Standard

**Rule:** `MEP-UNIFIED-MODEL-001`
**Status:** LOCKED

Mechanical production uses one graph-native source of truth after architecture recognition and before CAD materialization. The model binds individual bounded rooms, hosted endpoints, typed levels, network nodes and edges, segment calculations, plan identities, riser identities and schedule identities.

For every network edge the following identity is mandatory:

`network_edge_id -> calc_id = plan_id = riser_id = schedule_id`

Every calculation must name its edge and provenance. Every connected endpoint must appear in at least one graph-derived plan branch. An orphan calculation, dangling edge, divergent output identity, duplicate room identity, missing provenance, or zero plan branches with connected endpoints blocks generation.

The public Plan, M-151 riser register, M-152 calculation register and schedules are projections of this model. They may not independently reconstruct branches or substitute generic project-context routes. Architecture and questionnaire facts retain their provenance; private reference drawings remain forbidden generation inputs.

The first revision is backward-compatible with PMM v3 storage: it adds individual room records and the `unified_model_contract` without deleting legacy fields. Existing projects are reanalysed on their next generation so the unified model is created from the current approved architecture, answers and design basis.
