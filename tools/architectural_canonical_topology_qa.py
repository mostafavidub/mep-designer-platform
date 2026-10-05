"""Render auditable SVG overlays from a canonical architecture JSON artifact."""
from __future__ import annotations

import html
import json
from pathlib import Path
import sys

from shapely.geometry import LineString, box


def _svg(bounds, body):
    minx,miny,maxx,maxy=bounds; width=maxx-minx; height=maxy-miny
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {-maxy} {width} {height}">'
            f'<style>text{{font:{max(height*.012,.001)}px sans-serif;paint-order:stroke;stroke:white;stroke-width:3px;vector-effect:non-scaling-stroke}}'
            'path,line,polygon{vector-effect:non-scaling-stroke}</style>' + body + '</svg>')


def _points(points):
    return " ".join(f"{x},{-y}" for x,y in points)


def _write(root,frame_id,index,name,bounds,body):
    (root/f'{frame_id}-{index:02d}-{name}.svg').write_text(_svg(bounds,body))


def main(source, output):
    model=json.loads(Path(source).read_text()); root=Path(output); root.mkdir(parents=True,exist_ok=True)
    frames={f['frame_id']:f for f in model['frames'] if f.get('bounds')}
    for frame_id,frame in frames.items():
        walls=[w for w in model['canonical_walls'] if w['frame_id']==frame_id]
        spaces=[s for s in model['physical_spaces'] if s['frame_id']==frame_id]
        envelope=next((e for e in model['building_envelopes'] if e['frame_id']==frame_id),None)
        if not walls and not spaces: continue
        raw=''.join(f'<line x1="{r["geometry"][0][0]}" y1="{-r["geometry"][0][1]}" x2="{r["geometry"][-1][0]}" y2="{-r["geometry"][-1][1]}" stroke="#d1d5db" stroke-width="1"/>' for r in model['architectural_segments'] if r.get('frame_id')==frame_id)
        wall_body=raw
        for wall in walls:
            wall_body+=f'<polyline points="{_points(wall["centerline"])}" fill="none" stroke="#2563eb" stroke-width="2"/>'
            x,y=wall['centerline'][0]; wall_body+=f'<text x="{x}" y="{-y}" fill="#1e3a8a">{html.escape(wall["wall_id"][-6:])}</text>'
            for gap in wall.get('interruptions',[]):
                origin=wall['wall_solid']['axis_origin']; u=wall['wall_solid']['axis_direction']; a,b=gap['interval']
                points=[[origin[0]+a*u[0],origin[1]+a*u[1]],[origin[0]+b*u[0],origin[1]+b*u[1]]]
                wall_body+=f'<line x1="{points[0][0]}" y1="{-points[0][1]}" x2="{points[1][0]}" y2="{-points[1][1]}" stroke="#dc2626" stroke-width="5"/>'
        _write(root,frame_id,1,'wall-objects',frame['bounds'],wall_body)
        face_body=raw
        for wall in walls:
            for key,color in (('face_a','#7c3aed'),('face_b','#db2777')):
                if wall.get(key): face_body+=f'<polyline points="{_points(wall[key])}" fill="none" stroke="{color}" stroke-width="2"/>'
        _write(root,frame_id,2,'wall-faces-and-solids',frame['bounds'],face_body)
        interruption_body=wall_body
        _write(root,frame_id,3,'wall-interruptions',frame['bounds'],interruption_body)
        env_body=raw
        if envelope and envelope['outer_ring']:
            env_body+=f'<polygon points="{_points(envelope["outer_ring"])}" fill="#16a34a22" stroke="#16a34a" stroke-width="3"/>'
        _write(root,frame_id,4,'building-envelope',frame['bounds'],env_body)
        barrier_body=raw
        for barrier in model.get('enclosure_barrier_graph',{}).get('barriers',[]):
            if not LineString(barrier['geometry']).intersects(box(*frame['bounds'])): continue
            color={'ENVELOPE':'#16a34a','WALL_MATERIAL':'#2563eb','VIRTUAL_CLOSURE':'#dc2626','VOID':'#7c3aed'}.get(barrier['kind'],'#111827')
            barrier_body+=f'<polyline points="{_points(barrier["geometry"])}" fill="none" stroke="{color}" stroke-width="2"/>'
        _write(root,frame_id,5,'enclosure-barrier-graph',frame['bounds'],barrier_body)
        space_body=raw
        for space in spaces:
            color='#16a34a' if space['status']=='VERIFIED' else '#d97706'
            space_body+=f'<polygon points="{_points(space["polygon"])}" fill="{color}22" stroke="{color}" stroke-width="2"/>'
            x,y=space['centroid']; space_body+=f'<text x="{x}" y="{-y}" fill="#111827">{html.escape(space["category"])} · {space["physical_space_id"][-6:]}</text>'
        _write(root,frame_id,6,'raw-subdivision-cells',frame['bounds'],space_body)
        _write(root,frame_id,7,'final-physical-spaces',frame['bounds'],space_body)
        labels=space_body
        for label in model.get('label_bindings',[]):
            x,y=label['point']; color='#16a34a' if label['status']=='VERIFIED' else '#dc2626'
            radius=max((frame['bounds'][3]-frame['bounds'][1])*.003,.001)
            labels+=f'<circle cx="{x}" cy="{-y}" r="{radius}" fill="{color}"/><text x="{x}" y="{-y}" fill="{color}">{html.escape(label["text"])}</text>'
        _write(root,frame_id,8,'label-hosting',frame['bounds'],labels)
        _write(root,frame_id,9,'vision-space-reconciliation',frame['bounds'],space_body)
        portals=space_body
        for opening in model.get('openings',[]):
            geometry=opening.get('geometry') or opening.get('line')
            if geometry: portals+=f'<polyline points="{_points(geometry)}" fill="none" stroke="#dc2626" stroke-width="4"/>'
        _write(root,frame_id,10,'portal-hosting',frame['bounds'],portals)
        _write(root,frame_id,11,'final-architecture',frame['bounds'],labels+portals)
    print(root)


if __name__ == '__main__':
    main(sys.argv[1],sys.argv[2])
