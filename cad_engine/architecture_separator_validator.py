"""Read-only separator checks independent from producer qualification predicates."""
import math
from copy import deepcopy
from shapely.geometry import LineString, Polygon
from shapely.ops import substring, unary_union
from .architecture_contract import content_hash
from .architecture_review_contract import validate_review_decision


def separator_errors(model):
    errors = []
    receipts = {(r.get('review_fingerprint'), r.get('decision')) for r in (model.get('review_registry') or {}).get('accepted_decisions', []) if r.get('applied')}
    registry = {}
    rejected_regions = {}
    for row in model.get('evidence_registry', []):
        if row.get('kind') != 'SOURCE_BOUNDARY_SUPPORT': continue
        key = row.get('evidence_id')
        if key in registry: errors.append(('SEPARATOR_DUPLICATE_WITNESS', key))
        registry[key] = row
    for row in model.get('evidence_registry', []):
        if row.get('kind') != 'SOURCE_REVIEW_REGION': continue
        key = row.get('evidence_id'); p = row.get('payload') or {}
        identity = {k: deepcopy(p.get(k)) for k in ('source_sha256','frame_id','geometry_fingerprint','source_handles','question','allowed_interpretations','packet_fingerprint','scope','region_fingerprints')}
        fingerprint = content_hash(identity)
        if p.get('source_sha256') != model.get('source', {}).get('source_sha256') or p.get('evidence_fingerprint') != fingerprint or key != 'SOURCE-REGION-' + fingerprint[:24].upper():
            errors.append(('REGION_REVIEW_BINDING_STALE', key))
        interpretation = p.get('interpretation')
        if interpretation:
            item = interpretation.get('review_item') or {}
            current = dict(source_sha256=p.get('source_sha256'), frame_or_level_id=p.get('frame_id'), object_or_region_id=key,
                           geometry_fingerprint=p.get('geometry_fingerprint'), evidence_fingerprint=fingerprint, review_scope='SOURCE_REGION_INTERPRETATION')
            if interpretation.get('separator_authority') is not False or validate_review_decision(item, interpretation.get('decision'), current)['status'] != 'ACCEPTED':
                errors.append(('REGION_REVIEW_SCOPE_INVALID', key))
            if (item.get('review_fingerprint'), interpretation.get('decision')) not in receipts:
                errors.append(('REGION_REVIEW_RECEIPT_MISSING', key))
            if interpretation.get('decision') == 'NOT_INDEPENDENT_SPACE' and not any(e[1] == key for e in errors):
                for fingerprint in p.get('region_fingerprints', []): rejected_regions[fingerprint] = key
    invalid = set()
    for key, row in registry.items():
        p = row.get('payload') or {}; role = p.get('separator') or {}
        identity = {k: deepcopy(p.get(k)) for k in ('policy', 'source_sha256', 'frame_id', 'level_id',
                    'source_handle', 'segment_id', 'occurrence', 'geometry', 'interval', 'negative_evidence', 'source_role_evidence')}
        expected = content_hash(identity)
        reasons = []
        if p.get('policy') != 'planha-separator-evidence/1.0' or p.get('source_sha256') != model.get('source', {}).get('source_sha256'):
            reasons.append('SEPARATOR_SOURCE_BINDING_INVALID')
        if not p.get('source_handle') or not p.get('segment_id') or not p.get('frame_id'):
            reasons.append('SEPARATOR_SOURCE_REFERENCE_MISSING')
        if expected != p.get('evidence_fingerprint') or key != 'BOUNDARY-' + expected[:24].upper():
            reasons.append('SEPARATOR_EVIDENCE_STALE')
        if p.get('geometry_fingerprint') != content_hash([p.get('geometry'), p.get('occurrence'), p.get('interval')]):
            reasons.append('SEPARATOR_GEOMETRY_STALE')
        try:
            if len(p['geometry']) != 2 or any(not math.isfinite(float(v)) for point in p['geometry'] for v in point): raise ValueError()
            if LineString(p['geometry']).length <= 0 or not 0 <= p['interval'][0] < p['interval'][1] <= 1: raise ValueError()
        except (KeyError, TypeError, ValueError, IndexError): reasons.append('SEPARATOR_GEOMETRY_INVALID')
        if role.get('role') not in {'UNKNOWN', 'PHYSICAL_SEPARATOR', 'NON_SEPARATOR'} or role.get('status') not in {'VERIFIED','SUPPORTED','AMBIGUOUS','INPUT_REQUIRED','CONFLICT','REJECTED'}:
            reasons.append('SEPARATOR_ROLE_INVALID')
        if role.get('status') in {'VERIFIED', 'REJECTED'}:
            if (role.get('status') == 'VERIFIED' and role.get('role') != 'PHYSICAL_SEPARATOR') or p.get('negative_evidence'):
                reasons.append('SEPARATOR_ROLE_CONFLICT')
            origin = role.get('origin')
            if origin == 'HUMAN_SOURCE_INTERPRETATION':
                item = role.get('review_item') or {}
                current = dict(source_sha256=p.get('source_sha256'), frame_or_level_id=p.get('frame_id'),
                               object_or_region_id=key, geometry_fingerprint=p.get('geometry_fingerprint'),
                               evidence_fingerprint=p.get('evidence_fingerprint'), review_scope='SOURCE_INTERVAL_SEPARATOR_ROLE')
                if item.get('question_type') != 'SOURCE_ROLE_CLASSIFICATION' or validate_review_decision(item, role.get('decision'), current)['status'] != 'ACCEPTED' or role.get('decision') != role.get('role'):
                    reasons.append('SEPARATOR_REVIEW_INVALID')
                if (item.get('review_fingerprint'), role.get('decision')) not in receipts:
                    reasons.append('SEPARATOR_REVIEW_RECEIPT_MISSING')
            elif origin == 'STRUCTURED_INPUT':
                assertion = role.get('assertion') or {}
                if model.get('source', {}).get('source_type') == 'RAW_DXF' or assertion.get('source_sha256') != p.get('source_sha256') or assertion.get('evidence_fingerprint') != expected or not assertion.get('profile_id'):
                    reasons.append('SEPARATOR_STRUCTURED_PROVENANCE_INVALID')
            else: reasons.append('SEPARATOR_ROLE_PROVENANCE_MISSING')
        if reasons:
            invalid.add(key); errors.extend((reason, key) for reason in reasons)
    for space in model.get('physical_spaces', []):
        proof = space.get('geometry_evidence') or {}; sid = space.get('physical_space_id')
        granted = bool((space.get('authority') or {}).get('material_geometry'))
        fingerprint = content_hash([space.get('frame_id'), space.get('polygon'), space.get('interior_rings') or []])
        region = rejected_regions.get(fingerprint)
        if region and granted: errors.append(('REVIEWED_NON_SPACE_MATERIAL_AUTHORITY', sid))
        if space.get('independent_space_status') == 'REJECTED' and (not region or space.get('region_interpretation_evidence_id') != region):
            errors.append(('REGION_REJECTION_WITHOUT_EVIDENCE', sid))
        support = []; negative = []; refs = proof.get('boundary_witnesses') or []
        try:
            polygon = Polygon(space['polygon'], space.get('interior_rings') or [])
            rings = [polygon.exterior] + list(polygon.interiors)
            tol = float(proof.get('tolerance') or 1e-7)
            scale = float(model.get('source', {}).get('effective_scale') or 1.)
            if not math.isfinite(tol) or not 0 < tol <= .2 / scale: raise ValueError()
            for ref in refs:
                key = ref.get('evidence_id'); entry = registry.get(key)
                if not entry or key in invalid:
                    errors.append(('SEPARATOR_WITNESS_REFERENCE_INVALID', sid)); continue
                p = entry['payload']; lo, hi = ref['source_interval']; blo, bhi = ref['boundary_interval']
                points = list(rings[ref['ring']].coords); index = ref['edge']
                if ref['ring'] < 0 or index < 0 or not 0 <= blo < bhi <= 1 or not p['interval'][0] <= lo <= hi <= p['interval'][1]: raise ValueError()
                if p['frame_id'] != space.get('frame_id') or p['level_id'] != space.get('level_id') or ref.get('derivation') != 'DIRECT': raise ValueError()
                edge = substring(LineString([points[index], points[index+1]]), blo, bhi, normalized=True)
                source = substring(LineString(p['geometry']), lo, hi, normalized=True)
                if edge.difference(source.buffer(tol)).length > 1e-9: raise ValueError()
                role = p.get('separator') or {}
                if role.get('role') == 'NON_SEPARATOR' and role.get('status') == 'REJECTED': negative.append(source)
                if role.get('role') == 'PHYSICAL_SEPARATOR' and role.get('status') == 'VERIFIED' and not p.get('negative_evidence'):
                    support.append(source)
            if proof.get('separator_status') == 'REJECTED' and not negative:
                errors.append(('SEPARATOR_REJECTION_WITHOUT_EVIDENCE', sid))
            if (granted or proof.get('separator_status') == 'VERIFIED') and (proof.get('status') != 'VERIFIED' or proof.get('negative_evidence') or not support or polygon.boundary.difference(unary_union(support).buffer(tol)).length > 1e-9):
                errors.append(('MATERIAL_AUTHORITY_WITHOUT_SEPARATOR_EVIDENCE', sid))
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            errors.append(('SEPARATOR_INTERVAL_INVALID', sid))
    return sorted(set(errors))
