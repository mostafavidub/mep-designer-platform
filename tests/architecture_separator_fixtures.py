"""Explicit structured role fixture for tests of downstream review mechanics.

This is not DXF inference or benchmark truth; each synthetic edge is declared
as a separator by the test author.
"""
from cad_engine.architecture_separator_evidence import bind_boundary, refresh_separator_authority


def declare_structured_separators(model):
    model['schema']='planha-canonical-architecture/3.0'
    model['source']['source_type']='CERTIFIED_DXF'
    for space in model.get('physical_spaces', []):
        rings=[space['polygon']]+space.get('interior_rings', [])
        records=[]
        for ri, ring in enumerate(rings):
            points=ring[:-1] if ring[0]==ring[-1] else ring
            for i,(a,b) in enumerate(zip(points,points[1:]+points[:1])):
                records.append(dict(segment_id=f'{space["physical_space_id"]}-{ri}-{i}',source_handle=f'SYNTHETIC-{ri}-{i}',geometry=[a,b]))
        space['geometry_status']='VERIFIED'
        space['source_handles']=[r['source_handle'] for r in records]
        space['geometry_evidence']=dict(status='VERIFIED',source_handles=space['source_handles'],segments=[r['geometry'] for r in records],tolerance=.001,source_witness_records=records)
        evidence=bind_boundary(space,model['source']['source_sha256'])
        for e in evidence:
            p=e['payload'];p['separator']=dict(role='PHYSICAL_SEPARATOR',status='VERIFIED',origin='STRUCTURED_INPUT',assertion=dict(source_sha256=p['source_sha256'],evidence_fingerprint=p['evidence_fingerprint'],profile_id='TEST-AUTHORED-SEPARATORS'))
        model.setdefault('evidence_registry',[]).extend(evidence)
    refresh_separator_authority(model)
    return model
