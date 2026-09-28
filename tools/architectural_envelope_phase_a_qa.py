"""Generate the Phase-A envelope diagnostic table and auditable SVG overlays."""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path
import sys


COLORS={"BUILDING_INTERIOR":"#16a34a","SEMI_EXTERIOR":"#d97706","SITE_EXTERIOR":"#2563eb",
        "COURTYARD":"#7c3aed","LIGHTWELL":"#9333ea","VOID":"#6b7280","UNKNOWN":"#dc2626"}


def _points(points): return " ".join(f"{x},{-y}" for x,y in points)


def _svg(bounds,body):
    minx,miny,maxx,maxy=bounds; width=maxx-minx; height=maxy-miny
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {-maxy} {width} {height}">'
            '<style>*{vector-effect:non-scaling-stroke}text{font-size:.18px;font-family:sans-serif;paint-order:stroke;stroke:white;stroke-width:2px}</style>'
            +body+'</svg>')


def _raw(model,frame_id):
    return ''.join(f'<line x1="{row["geometry"][0][0]}" y1="{-row["geometry"][0][1]}" x2="{row["geometry"][-1][0]}" y2="{-row["geometry"][-1][1]}" stroke="#9ca3af" stroke-width=".7"/>'
                   for row in model["architectural_segments"] if row.get("frame_id")==frame_id)


def main(source,output):
    model=json.loads(Path(source).read_text()); root=Path(output); root.mkdir(parents=True,exist_ok=True)
    candidates={row["frame_id"]:row["candidates"] for row in model.get("building_envelope_candidates") or []}
    regions=model.get("plan_regions",{}).get("regions") or []
    selected={row["frame_id"]:row for row in model.get("building_envelopes") or []}
    rows=[]
    for frame in model["frames"]:
        fid=frame["frame_id"]
        if fid not in candidates or not frame.get("bounds"): continue
        raw=_raw(model,fid); frame_regions=[row for row in regions if row["frame_id"]==fid]
        candidate_body=raw
        for index,row in enumerate(candidates[fid],start=1):
            candidate_body+=f'<polygon points="{_points(row["polygon"])}" fill="#f59e0b18" stroke="#f59e0b" stroke-width="1"/><text x="{row["polygon"][0][0]}" y="{-row["polygon"][0][1]}">C{index} A={row["area"]:.2f}</text>'
            rows.append(row)
        evidence_body=candidate_body
        for index,row in enumerate(candidates[fid],start=1):
            x,y=row["polygon"][0]; evidence_body+=f'<text x="{x}" y="{-y-.22}">C{index}: labels={row["semantic_categories"]}; internal={row["internal_partition_count"]}; DF={row["boundary_double_face_ratio"]:.2f}</text>'
        envelope_body=raw; envelope=selected.get(fid)
        if envelope and envelope.get("outer_ring"):
            envelope_body+=f'<polygon points="{_points(envelope["outer_ring"])}" fill="#16a34a22" stroke="#16a34a" stroke-width="3"/>'
        else:
            envelope_body+=f'<text x="{frame["bounds"][0]+.3}" y="{-frame["bounds"][3]+.5}" fill="#dc2626">NO DEFENSIBLE BUILDING ENVELOPE: {html.escape((envelope or {}).get("reason","UNKNOWN"))}</text>'
        role_bodies={role:raw for role in COLORS}
        final_body=raw
        for row in frame_regions:
            color=COLORS[row["role"]]; shape=f'<polygon points="{_points(row["geometry"])}" fill="{color}33" stroke="{color}" stroke-width="2"/>'
            role_bodies[row["role"]]+=shape; final_body+=shape
            x,y=row["geometry"][0]; final_body+=f'<text x="{x}" y="{-y}" fill="{color}">{row["role"]}</text>'
        outputs=[("01-envelope-candidates",candidate_body),("02-envelope-candidate-evidence",evidence_body),
                 ("03-selected-building-envelope",envelope_body),("04-building-interior-regions",role_bodies["BUILDING_INTERIOR"]),
                 ("05-semi-exterior-regions",role_bodies["SEMI_EXTERIOR"]),("06-site-exterior-regions",role_bodies["SITE_EXTERIOR"]),
                 ("07-courtyard-lightwell-voids",role_bodies["COURTYARD"]+role_bodies["LIGHTWELL"]+role_bodies["VOID"]),
                 ("08-final-region-classification",final_body)]
        for name,body in outputs: (root/f'{fid}-{name}.svg').write_text(_svg(frame["bounds"],body))
    (root/'envelope-candidates.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    if rows:
        with (root/'envelope-candidates.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=sorted(rows[0])); writer.writeheader()
            for row in rows: writer.writerow({key:json.dumps(value,ensure_ascii=False) if isinstance(value,(list,dict)) else value for key,value in row.items()})
    (root/'summary.json').write_text(json.dumps({"head":model.get("source",{}).get("source_sha256"),"envelopes":model.get("building_envelopes"),"region_coverage":model.get("region_coverage")},ensure_ascii=False,indent=2))
    print(root)


if __name__=='__main__': main(sys.argv[1],sys.argv[2])
