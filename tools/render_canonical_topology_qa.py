"""Render auditable SVG overlays from a canonical architecture JSON artifact."""
from __future__ import annotations

import html
import json
from pathlib import Path
import sys


def _svg(bounds, body):
    minx,miny,maxx,maxy=bounds; width=maxx-minx; height=maxy-miny
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {-maxy} {width} {height}">'
            '<style>text{font:12px sans-serif;paint-order:stroke;stroke:white;stroke-width:3px;vector-effect:non-scaling-stroke}'
            'path,line,polygon{vector-effect:non-scaling-stroke}</style>' + body + '</svg>')


def _points(points):
    return " ".join(f"{x},{-y}" for x,y in points)


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
        (root/f'{frame_id}-walls.svg').write_text(_svg(frame['bounds'],wall_body))
        env_body=raw
        if envelope and envelope['outer_ring']:
            env_body+=f'<polygon points="{_points(envelope["outer_ring"])}" fill="#16a34a22" stroke="#16a34a" stroke-width="3"/>'
        (root/f'{frame_id}-envelope.svg').write_text(_svg(frame['bounds'],env_body))
        space_body=raw
        for space in spaces:
            color='#16a34a' if space['status']=='VERIFIED' else '#d97706'
            space_body+=f'<polygon points="{_points(space["polygon"])}" fill="{color}22" stroke="{color}" stroke-width="2"/>'
            x,y=space['centroid']; space_body+=f'<text x="{x}" y="{-y}" fill="#111827">{html.escape(space["category"])} · {space["physical_space_id"][-6:]}</text>'
        (root/f'{frame_id}-spaces.svg').write_text(_svg(frame['bounds'],space_body))
    print(root)


if __name__ == '__main__':
    main(sys.argv[1],sys.argv[2])
