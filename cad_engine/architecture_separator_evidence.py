"""Source-owned role evidence and interval references; never a geometry author.

Raw drafting context is deliberately not a physical-separator assertion. This
module produces evidence; the independent validator checks its consumption.
"""
from copy import deepcopy

from shapely.geometry import LineString, Polygon, Point
from shapely.ops import substring, unary_union

from .architecture_contract import content_hash

POLICY = 'planha-separator-evidence/1.0'
KIND = 'SOURCE_BOUNDARY_SUPPORT'
SCOPE = 'SOURCE_INTERVAL_SEPARATOR_ROLE'


def source_identity(payload):
    return {k: deepcopy(payload.get(k)) for k in
            ('policy', 'source_sha256', 'frame_id', 'level_id', 'source_handle',
             'segment_id', 'occurrence', 'geometry', 'interval', 'negative_evidence', 'source_role_evidence')}


def witness(row, source_sha, frame_id, level_id, interval=(0., 1.)):
    points = sorted([list(row['geometry'][0]), list(row['geometry'][-1])])
    payload = dict(policy=POLICY, source_sha256=source_sha, frame_id=frame_id,
                   level_id=level_id, source_handle=row.get('source_handle'),
                   segment_id=row.get('segment_id'), geometry=points,
                   occurrence={k: deepcopy(row.get(k)) for k in
                               ('source_insert_handle', 'source_block_path', 'source_transform')},
                   interval=list(interval), negative_evidence=deepcopy(row.get('negative_evidence') or []),
                   source_role_evidence={'classification': deepcopy(row.get('pre_topology_classification') or {}),
                                         'support': deepcopy(row.get('evidence') or [])})
    payload['geometry_fingerprint'] = content_hash([points, payload['occurrence'], list(interval)])
    payload['evidence_fingerprint'] = content_hash(source_identity(payload))
    payload['separator'] = {'role': 'UNKNOWN', 'status': 'AMBIGUOUS', 'origin': 'SOURCE_GEOMETRIC'}
    return {'evidence_id': 'BOUNDARY-' + payload['evidence_fingerprint'][:24].upper(),
            'origin': 'SOURCE_GEOMETRIC', 'kind': KIND, 'payload': payload}


def bind_boundary(space, source_sha):
    """Bind only exact admitted source records, not derived wall-axis guesses."""
    proof = space.setdefault('geometry_evidence', {})
    records = proof.pop('source_witness_records', [])
    registry = {}
    refs = []
    polygon = Polygon(space['polygon'], space.get('interior_rings') or [])
    tol = float(proof.get('tolerance') or 1e-7)
    for row in records:
        entry = witness(row, source_sha, space.get('frame_id'), space.get('level_id'))
        payload = entry['payload']; line = LineString(payload['geometry'])
        if line.length <= 0:
            continue
        for ring_index, ring in enumerate([polygon.exterior] + list(polygon.interiors)):
            points = list(ring.coords)
            for edge_index, (a, b) in enumerate(zip(points, points[1:])):
                edge = LineString([a, b]); covered = edge.intersection(line.buffer(tol))
                parts = list(covered.geoms) if hasattr(covered, 'geoms') else [covered]
                for part in parts:
                    if part.geom_type != 'LineString' or part.length <= 1e-12:
                        continue
                    lo, hi = sorted(edge.project(Point(p), normalized=True)
                                    for p in (part.coords[0], part.coords[-1]))
                    source_range = sorted(line.project(Point(p), normalized=True)
                                          for p in (part.coords[0], part.coords[-1]))
                    if source_range[1] - source_range[0] <= 1e-12:
                        continue
                    refs.append({'evidence_id': entry['evidence_id'], 'ring': ring_index,
                                 'edge': edge_index, 'boundary_interval': [lo, hi],
                                 'source_interval': source_range, 'derivation': 'DIRECT'})
                    registry[entry['evidence_id']] = entry
    proof['boundary_witnesses'] = sorted(refs, key=content_hash)
    proof['separator_status'] = 'AMBIGUOUS' if refs else 'INPUT_REQUIRED'
    proof['separator_policy'] = POLICY
    return list(registry.values())


def review_candidate(entry):
    p = entry['payload']
    return {'question_type': 'SOURCE_ROLE_CLASSIFICATION', 'object_or_region_id': entry['evidence_id'],
            'frame_or_level_id': p['frame_id'], 'geometry_fingerprint': p['geometry_fingerprint'],
            'evidence_fingerprint': p['evidence_fingerprint'], 'review_scope': SCOPE,
            'allowed_answers': ['PHYSICAL_SEPARATOR', 'NON_SEPARATOR', 'UNKNOWN'],
            'candidate_interpretations': ['PHYSICAL_SEPARATOR', 'NON_SEPARATOR', 'UNKNOWN'],
            'can_resolve_without_geometry_creation': True, 'existing_source_evidence': True,
            'evidence_summary': {'source_handles': [p['source_handle']], 'segment_ids': [p['segment_id']],
                                 'interval': p['interval'], 'negative_evidence': p['negative_evidence']},
            'preview_spec': {'frame_id': p['frame_id'], 'highlight_geometry': p['geometry'],
                             'source_handles': [p['source_handle']],
                             'question_focus': 'Does this existing source interval represent a physical separator?'}}


def _current_role_state(entry, model, receipts):
    p = entry['payload']; role = p.get('separator') or {}
    if p.get('source_sha256') != model.get('source', {}).get('source_sha256') or p.get('evidence_fingerprint') != content_hash(source_identity(p)):
        return 'CONFLICT'
    state = role.get('status', 'AMBIGUOUS')
    if state in {'VERIFIED', 'REJECTED'}:
        if role.get('origin') == 'HUMAN_SOURCE_INTERPRETATION':
            from .architecture_review_contract import validate_review_decision
            current = review_candidate(entry)
            current['source_sha256'] = p['source_sha256']
            item = role.get('review_item') or {}
            receipt = (item.get('review_fingerprint'), role.get('decision')) in receipts
            if not receipt or role.get('decision') != role.get('role') or validate_review_decision(item, role.get('decision'), current)['status'] != 'ACCEPTED':
                return 'CONFLICT'
        elif role.get('origin') == 'STRUCTURED_INPUT':
            assertion = role.get('assertion') or {}
            if model.get('source', {}).get('source_type') == 'RAW_DXF' or assertion.get('source_sha256') != p['source_sha256'] or assertion.get('evidence_fingerprint') != p['evidence_fingerprint'] or not assertion.get('profile_id'):
                return 'CONFLICT'
        else:
            return 'CONFLICT'
    if role.get('role') == 'NON_SEPARATOR' and state == 'REJECTED': return 'REJECTED'
    if state == 'VERIFIED' and role.get('role') != 'PHYSICAL_SEPARATOR': return 'CONFLICT'
    return state


def region_geometry_fingerprint(space):
    return content_hash([space.get('frame_id'), space.get('polygon'), space.get('interior_rings') or []])


def _negative_regions(model, receipts):
    from .architecture_review_contract import validate_review_decision
    denied = {}
    for entry in model.get('evidence_registry', []):
        if entry.get('kind') != 'SOURCE_REVIEW_REGION': continue
        p = entry['payload']; interpretation = p.get('interpretation') or {}
        if interpretation.get('decision') != 'NOT_INDEPENDENT_SPACE': continue
        item = interpretation.get('review_item') or {}
        identity = {k: deepcopy(p.get(k)) for k in ('source_sha256','frame_id','geometry_fingerprint','source_handles','question','allowed_interpretations','packet_fingerprint','scope','region_fingerprints')}
        if p.get('evidence_fingerprint') != content_hash(identity) or p.get('source_sha256') != model.get('source', {}).get('source_sha256'): continue
        current = dict(source_sha256=p['source_sha256'], frame_or_level_id=p['frame_id'], object_or_region_id=entry['evidence_id'],
                       geometry_fingerprint=p['geometry_fingerprint'], evidence_fingerprint=p['evidence_fingerprint'], review_scope='SOURCE_REGION_INTERPRETATION')
        if (item.get('review_fingerprint'), 'NOT_INDEPENDENT_SPACE') not in receipts or validate_review_decision(item, 'NOT_INDEPENDENT_SPACE', current)['status'] != 'ACCEPTED': continue
        for fingerprint in p.get('region_fingerprints', []): denied[fingerprint] = entry['evidence_id']
    return denied


def refresh_separator_authority(model):
    """Recompute interval authority; non-separators never veto other valid witnesses."""
    evidence = {r['evidence_id']: r for r in model.get('evidence_registry', []) if r.get('kind') == KIND}
    receipts = {(r.get('review_fingerprint'), r.get('decision')) for r in (model.get('review_registry') or {}).get('accepted_decisions', []) if r.get('applied')}
    states = {key: _current_role_state(entry, model, receipts) for key, entry in evidence.items()}
    denied = _negative_regions(model, receipts)
    pending = {}
    for space in model.get('physical_spaces', []):
        proof = space.get('geometry_evidence') or {}
        region = denied.get(region_geometry_fingerprint(space))
        if region:
            space['independent_space_status'] = 'REJECTED'
            space['region_interpretation_evidence_id'] = region
            space.setdefault('authority', {}).update(status='REJECTED', material_geometry=False)
            continue
        space.pop('independent_space_status', None)
        space.pop('region_interpretation_evidence_id', None)
        refs = proof.get('boundary_witnesses') or []
        poly = Polygon(space['polygon'], space.get('interior_rings') or [])
        tol = float(proof.get('tolerance') or 1e-7)
        geometry = []; supported = []; unknown = []; ambiguous = {}; conflict = False
        for ref in refs:
            entry = evidence.get(ref['evidence_id'])
            if not entry:
                conflict = True; continue
            p = entry['payload']; state = states[entry['evidence_id']]
            part = substring(LineString(p['geometry']), *ref['source_interval'], normalized=True)
            geometry.append(part)
            if p.get('negative_evidence'): state = 'CONFLICT'
            if state == 'VERIFIED': supported.append(part)
            elif state in {'AMBIGUOUS', 'SUPPORTED'}:
                unknown.append(part); ambiguous[entry['evidence_id']] = entry
            elif state == 'CONFLICT': conflict = True
        missing = poly.boundary if not supported else poly.boundary.difference(unary_union(supported).buffer(tol))
        geometry_missing = poly.boundary if not geometry else poly.boundary.difference(unary_union(geometry).buffer(tol))
        if conflict: state = 'CONFLICT'
        elif proof.get('status') != 'VERIFIED' or geometry_missing.length > 1e-9: state = 'INPUT_REQUIRED'
        elif missing.length <= 1e-9: state = 'VERIFIED'
        elif unknown and missing.difference(unary_union(unknown).buffer(tol)).length <= 1e-9: state = 'AMBIGUOUS'
        else: state = 'REJECTED'
        proof['separator_status'] = state
        authority = space.setdefault('authority', {})
        granted = state == 'VERIFIED' and not proof.get('negative_evidence')
        authority['material_geometry'] = granted
        authority['status'] = 'VERIFIED' if granted else state
        if state == 'AMBIGUOUS':
            for key, entry in ambiguous.items():
                if missing.intersection(LineString(entry['payload']['geometry']).buffer(tol)).length <= 1e-9: continue
                pending[key] = {'unresolved_item_id': 'SEPARATOR-' + key, 'object_or_region_id': key,
                                'issue_type': 'SEPARATOR_ROLE_REQUIRED', 'evidence': {'evidence_id': key},
                                'downstream_impact': 'BLOCKS_RELEASE', 'review_candidate': review_candidate(entry)}
        elif not granted and state != 'REJECTED':
            key = space['physical_space_id']
            pending[key] = {'unresolved_item_id': 'SEPARATOR-' + key, 'object_or_region_id': key,
                            'issue_type': 'SEPARATOR_' + state, 'evidence': {}, 'downstream_impact': 'BLOCKS_RELEASE'}
    model['unresolved_items'] = [r for r in model.get('unresolved_items', [])
                                 if not str(r.get('unresolved_item_id', '')).startswith('SEPARATOR-')] + list(pending.values())
    if pending:
        model['release'] = {'status': 'INPUT_REQUIRED', 'downstream_engineering_allowed': False, 'release_allowed': False}


def register_source_region_review(model, *, frame_id, geometry_fingerprint, source_handles,
                                  question, allowed_interpretations, evidence_fingerprint, region_fingerprints=()):
    """Trusted ingestion of an existing source review packet, not a client API.

    Region answers are retained at region scope. They NEVER classify individual
    boundary witnesses, even when the region has dependent room candidates.
    """
    payload = {'source_sha256': model['source']['source_sha256'], 'frame_id': frame_id,
               'geometry_fingerprint': geometry_fingerprint, 'source_handles': sorted(set(source_handles)),
               'question': question, 'allowed_interpretations': sorted(set(allowed_interpretations)),
               'packet_fingerprint': evidence_fingerprint, 'scope': 'SOURCE_REGION_INTERPRETATION',
               'region_fingerprints': sorted(set(region_fingerprints))}
    identity = content_hash(payload); key = 'SOURCE-REGION-' + identity[:24].upper()
    payload['evidence_fingerprint'] = identity
    existing = next((r for r in model.get('evidence_registry', []) if r['evidence_id'] == key), None)
    if existing is None:
        model.setdefault('evidence_registry', []).append({'evidence_id': key, 'kind': 'SOURCE_REVIEW_REGION',
                                                        'origin': 'SOURCE_GEOMETRIC', 'payload': payload})
    candidate = {'question_type': 'OTHER_BOUNDED_SOURCE_INTERPRETATION', 'object_or_region_id': key,
                 'frame_or_level_id': frame_id, 'geometry_fingerprint': geometry_fingerprint,
                 'evidence_fingerprint': identity, 'review_scope': payload['scope'],
                 'allowed_answers': payload['allowed_interpretations'],
                 'candidate_interpretations': payload['allowed_interpretations'],
                 'can_resolve_without_geometry_creation': True, 'existing_source_evidence': True,
                 'evidence_summary': {'question': question, 'source_handles': payload['source_handles']}}
    issue = {'unresolved_item_id': key, 'object_or_region_id': key, 'issue_type': 'SOURCE_REGION_INTERPRETATION',
             'evidence': {'packet_fingerprint': evidence_fingerprint}, 'review_candidate': candidate,
             'downstream_impact': 'REVIEW_CRITICAL'}
    if not any(r.get('unresolved_item_id') == key for r in model.get('unresolved_items', [])):
        model.setdefault('unresolved_items', []).append(issue)
    return key
