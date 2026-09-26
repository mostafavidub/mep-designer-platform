#!/usr/bin/env python3
"""Build source-only review material; never import reconstruction output."""
from __future__ import annotations
import argparse, html, json
from hashlib import sha256
from pathlib import Path
import ezdxf
from ezdxf.disassemble import recursive_decompose
from shapely.geometry import LineString, box
from shapely.ops import unary_union


def _points(entity):
    kind=entity.dxftype()
    try:
        if kind=="LINE": return [(float(entity.dxf.start.x),float(entity.dxf.start.y)),(float(entity.dxf.end.x),float(entity.dxf.end.y))]
        if kind=="LWPOLYLINE": return [(float(x),float(y)) for x,y,*_ in entity.get_points()]
        if kind=="POLYLINE": return [(float(v.dxf.location.x),float(v.dxf.location.y)) for v in entity.vertices]
        if kind in {"ARC","CIRCLE","ELLIPSE","SPLINE"}: return [(float(p.x),float(p.y)) for p in entity.flattening(.01)]
    except Exception: return []
    return []


def _text(entity):
    try:
        value=str(entity.dxf.text if entity.dxftype() in {"TEXT","ATTRIB","ATTDEF"} else entity.plain_text()).strip()
        point=entity.dxf.insert
        return value,(float(point.x),float(point.y)),float(getattr(entity.dxf,"height",.18) or .18)
    except Exception: return None


def _source_svg(doc,bounds,case_id):
    minx,miny,maxx,maxy=bounds; graphics=[]; texts=[]; counts={}; segments=[]; clip=box(minx,miny,maxx,maxy)
    for entity in recursive_decompose(doc.modelspace()):
        kind=entity.dxftype(); counts[kind]=counts.get(kind,0)+1; points=_points(entity)
        visible=points and max(x for x,_ in points)>=minx and min(x for x,_ in points)<=maxx and max(y for _,y in points)>=miny and min(y for _,y in points)<=maxy
        if visible:
            if bool(getattr(entity,"closed",False)) and points[0]!=points[-1]: points.append(points[0])
            encoded=" ".join(f"{x:.6f},{-y:.6f}" for x,y in points)
            graphics.append(f'<polyline points="{encoded}" fill="none" stroke="#263442" stroke-width="0.010" vector-effect="non-scaling-stroke"/>')
            if kind in {"LINE","LWPOLYLINE","POLYLINE"}:
                for start,end in zip(points,points[1:]):
                    if start!=end:
                        cut=LineString((start,end)).intersection(clip)
                        if not cut.is_empty:
                            if cut.geom_type=="LineString": segments.append(cut)
                            elif cut.geom_type=="MultiLineString": segments.extend(cut.geoms)
        label=_text(entity)
        if label:
            value,(x,y),height=label
            if minx<=x<=maxx and miny<=y<=maxy:
                texts.append(f'<text x="{x:.6f}" y="{-y:.6f}" font-size="{max(height,.08):.6f}" fill="#111827">{html.escape(value)}</text>')
    snap=set()
    if segments:
        noded=unary_union(segments)
        lines=[noded] if noded.geom_type=="LineString" else list(getattr(noded,"geoms",()))
        for line in lines:
            if line.geom_type=="LineString":
                for x,y in line.coords: snap.add((round(float(x),6),round(float(y),6)))
    counts["SNAP_POINTS"]=len(snap)
    snap_svg='<g id="snap-points">'+''.join(f'<circle class="snap-point" cx="{x:.6f}" cy="{-y:.6f}" r="0.04" data-x="{x:.6f}" data-y="{y:.6f}"/>' for x,y in sorted(snap))+'</g>'
    width=maxx-minx; height=maxy-miny
    svg=(f'<svg id="source-plan" xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {-maxy} {width} {height}" '
         f'data-case="{html.escape(case_id)}"><rect x="{minx}" y="{-maxy}" width="{width}" height="{height}" fill="white"/>'
         +"".join(graphics)+"".join(texts)+snap_svg+"</svg>")
    return svg,counts


def _viewer(svg,case_id,level,bounds,golden):
    initial=",".join(str(v) for v in (bounds[0],-bounds[3],bounds[2]-bounds[0],bounds[3]-bounds[1]))
    seed=json.dumps(golden,ensure_ascii=False).replace("</","<\\/")
    return f'''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>بازبینی مستقل پلان — {html.escape(case_id)}</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;height:100%;font:14px system-ui,-apple-system,sans-serif;color:#172033;background:#eef2f7}}
body{{display:grid;grid-template-rows:auto 1fr}}header{{background:#111827;color:#fff;padding:10px 16px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
header b{{font-size:16px}}.badge{{background:#334155;border-radius:999px;padding:5px 10px}}.safe{{background:#065f46}}#app{{min-height:0;display:grid;grid-template-columns:340px 1fr;direction:ltr}}
aside{{direction:rtl;background:#fff;border-left:1px solid #cbd5e1;padding:14px;overflow:auto}}main{{min-width:0;position:relative;background:#dbe3ed}}
h2{{font-size:17px;margin:0 0 8px}}h3{{font-size:14px;margin:18px 0 7px}}p{{line-height:1.7;margin:5px 0;color:#475569}}.step{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:10px;margin:8px 0}}
.tools{{display:grid;grid-template-columns:1fr 1fr;gap:7px}}button,.file-label,select,input{{font:inherit}}button,.file-label{{border:1px solid #94a3b8;background:#fff;border-radius:9px;padding:9px;cursor:pointer;text-align:center}}
button:hover,.file-label:hover{{background:#f1f5f9}}button.active{{background:#1d4ed8;color:#fff;border-color:#1d4ed8}}button.primary{{background:#059669;color:#fff;border-color:#047857;width:100%;font-weight:700}}button.danger{{color:#b91c1c}}
select,input{{width:100%;padding:9px;border:1px solid #cbd5e1;border-radius:8px;background:#fff}}label{{display:block;margin:8px 0 4px;color:#334155;font-weight:600}}#status{{padding:9px;border-radius:8px;background:#f1f5f9;margin:9px 0;line-height:1.6}}#canvas{{position:absolute;inset:0;overflow:hidden}}
svg{{width:100%;height:100%;touch-action:none;cursor:crosshair;background:#fff}}#source-plan polyline{{stroke:#334155!important;stroke-width:1.15px!important}}#source-plan text{{fill:#111827!important;font-weight:500}}.snap-point{{fill:#fff;stroke:#2563eb;stroke-width:1.5px;vector-effect:non-scaling-stroke;cursor:crosshair}}.snap-point:hover{{fill:#f59e0b;stroke:#b45309}}.ann{{vector-effect:non-scaling-stroke;stroke-width:2px}}.vertex{{vector-effect:non-scaling-stroke;stroke-width:1.5px}}
#help{{position:absolute;direction:rtl;left:14px;bottom:14px;background:#111827e8;color:#fff;border-radius:10px;padding:9px 12px;max-width:470px}}#empty{{color:#64748b}}.row{{display:flex;gap:7px}}.row>*{{flex:1}}
@media(max-width:850px){{#app{{grid-template-columns:1fr;grid-template-rows:45vh 1fr}}aside{{grid-row:2;border-left:0;border-top:1px solid #cbd5e1}}}}
</style><header data-source="RAW DXF ONLY"><b>بازبینی مستقل پلان</b><span class="badge">{html.escape(case_id)}</span><span class="badge">{html.escape(level)}</span><span class="badge safe">فقط نقشه خام؛ بدون خروجی موتور</span><span id="xy">مختصات: —</span></header>
<div id="app"><aside>
<h2>چه کاری باید انجام دهید؟</h2><div class="step">۱. ابتدا با ابزار <b>محدوده ساختمان</b> دور ساختمان را نقطه‌گذاری کنید.<br>۲. سپس هر <b>فضای واقعی</b> مثل اتاق، آشپزخانه یا راه‌پله را جدا رسم کنید.<br>۳. در پایان درها، پنجره‌ها و مسیرهای باز را علامت بزنید.<br><b>اگر مطمئن نیستید، نوع را «نامشخص» بگذارید.</b></div>
<h3>ابزار ترسیم</h3><div class="tools">
<button data-mode="pan" class="active">✋ جابه‌جایی پلان</button><button data-mode="envelope">⬡ محدوده ساختمان</button>
<button data-mode="space">▣ فضای واقعی</button><button data-mode="void">◌ حیاط‌خلوت / Void</button>
<button data-mode="door">🚪 در</button><button data-mode="window">▭ پنجره</button><button data-mode="passage">↔ مسیر باز</button><button id="fit">نمایش کامل پلان</button><button id="toggle-points">پنهان‌کردن نقاط آبی</button></div>
<div id="draw-options"><label>نوع فضا</label><select id="category"><option value="UNKNOWN">نامشخص / نیازمند بررسی</option><option value="living">پذیرایی / نشیمن</option><option value="dining">ناهارخوری</option><option value="kitchen">آشپزخانه</option><option value="bedroom">اتاق خواب</option><option value="bathroom">حمام</option><option value="toilet">سرویس بهداشتی</option><option value="corridor">راهرو / هال</option><option value="stair">راه‌پله</option><option value="elevator">آسانسور</option><option value="parking">پارکینگ</option><option value="balcony">بالکن / تراس</option><option value="shaft">شفت</option><option value="utility">فضای خدماتی</option><option value="exterior">فضای نیمه‌باز / بیرونی</option></select>
<label>نام نمایشی اختیاری</label><input id="label" placeholder="مثلاً اتاق خواب والدین"></div>
<div id="status">حالت جابه‌جایی فعال است. پلان را بکشید و با چرخ ماوس زوم کنید.</div>
<div class="row"><button id="finish" class="primary">بستن و ثبت محدوده</button><button id="undo">برگشت یک نقطه</button></div>
<h3>ذخیره و تحویل</h3><p>تغییرات در همین مرورگر خودکار ذخیره می‌شوند. برای تحویل، فایل را دانلود کنید.</p><button id="download" class="primary">دانلود فایل Golden</button>
<div class="row"><label class="file-label">بازکردن فایل قبلی<input id="import" type="file" accept="application/json" hidden></label><button id="clear" class="danger">پاک‌کردن پیش‌نویس</button></div>
<h3>خلاصه</h3><div id="summary"><span id="empty">هنوز چیزی ثبت نشده است.</span></div>
</aside><main><div id="canvas">{svg}</div><div id="help">در حالت جابه‌جایی، پلان را بکشید. در حالت ترسیم، روی گوشه‌ها کلیک کنید؛ نقاط نزدیک خطوط نقشه خودکار Snap می‌شوند.</div></main></div>
<script id="golden-seed" type="application/json">{seed}</script><script>
const s=document.querySelector('#source-plan'),xy=document.querySelector('#xy'),statusBox=document.querySelector('#status');
const initial=[{initial}],key='planha-golden-review:{html.escape(case_id)}';let view=[...initial],drag=null,mode='pan',draft=[],seq=1;
let golden=JSON.parse(localStorage.getItem(key)||document.querySelector('#golden-seed').textContent);
const NS='http://www.w3.org/2000/svg';const overlay=document.createElementNS(NS,'g');overlay.id='human-annotations';s.appendChild(overlay);
function applyView(){{s.setAttribute('viewBox',view.join(' '));const r=Math.max(view[2],view[3])*.0032;s.querySelectorAll('.snap-point').forEach(x=>x.setAttribute('r',r))}}applyView();
function svgPoint(e){{let p=s.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(s.getScreenCTM().inverse())}}
function sourcePoint(e){{const p=svgPoint(e);return [p.x,-p.y]}}
function snap(e){{let best=sourcePoint(e),dist=16;for(const point of s.querySelectorAll('.snap-point')){{const spt=s.createSVGPoint();spt.x=Number(point.dataset.x);spt.y=-Number(point.dataset.y);const c=spt.matrixTransform(s.getScreenCTM()),d=Math.hypot(c.x-e.clientX,c.y-e.clientY);if(d<dist){{dist=d;best=[spt.x,-spt.y]}}}}return best}}
function path(points,closed,color,fill='none'){{if(!points.length)return;const p=document.createElementNS(NS,closed?'polygon':'polyline');p.setAttribute('points',points.map(q=>q[0]+','+(-q[1])).join(' '));p.setAttribute('class','ann');p.setAttribute('stroke',color);p.setAttribute('fill',fill);overlay.appendChild(p);return p}}
function dot(point,color){{const c=document.createElementNS(NS,'circle');c.setAttribute('cx',point[0]);c.setAttribute('cy',-point[1]);c.setAttribute('r',Math.max(view[2],view[3])*.004);c.setAttribute('fill','#fff');c.setAttribute('stroke',color);c.setAttribute('class','vertex');overlay.appendChild(c)}}
function portalMark(item){{const colors={{door:'#ea580c',window:'#16a34a',open_passage:'#db2777'}},color=colors[item.kind],segment=item.opening_segment||[];if(segment.length===2){{const line=path(segment,false,color);line.setAttribute('stroke-width','5px');line.setAttribute('stroke-linecap','round')}}dot(item.point,color);const t=document.createElementNS(NS,'text');t.setAttribute('x',item.point[0]);t.setAttribute('y',-item.point[1]);t.setAttribute('dy','-8');t.setAttribute('fill',color);t.setAttribute('font-size',Math.max(view[2],view[3])*.018);t.setAttribute('font-weight','800');t.textContent={{door:'در',window:'پنجره',open_passage:'مسیر باز'}}[item.kind];overlay.appendChild(t)}}
function render(){{overlay.innerHTML='';const env=golden.building_envelope||{{}};path(env.outer_ring||[],true,'#7c3aed','#7c3aed18');(env.interior_voids||[]).forEach(x=>path(x,true,'#dc2626','#dc262618'));(golden.spaces||[]).forEach((x,i)=>path(x.polygon,true,'#0284c7',i%2?'#38bdf822':'#0ea5e922'));(golden.portals||[]).forEach(portalMark);path(draft,false,'#f59e0b');draft.forEach(x=>dot(x,'#f59e0b'));summary()}}
function save(){{localStorage.setItem(key,JSON.stringify(golden));render()}}
function summary(){{const n=(golden.spaces||[]).length,p=(golden.portals||[]).length,v=(golden.building_envelope?.interior_voids||[]).length;document.querySelector('#summary').innerHTML=`محدوده ساختمان: <b>${{golden.building_envelope?.outer_ring?.length?'ثبت شده':'ثبت نشده'}}</b><br>فضاها: <b>${{n}}</b><br>Voidها: <b>${{v}}</b><br>بازشوها: <b>${{p}}</b>`}}
function setMode(next){{mode=next;draft=[];document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));const msg={{pan:'پلان را بکشید و با چرخ ماوس زوم کنید.',envelope:'گوشه‌های بیرونی ساختمان را به ترتیب کلیک کنید.',space:'دور یک فضای واقعی را نقطه‌گذاری کنید.',void:'دور حیاط‌خلوت، نورگیر یا فضای خالی داخلی را مشخص کنید.',door:'روی دو سر دهانهٔ در کلیک کنید؛ پس از کلیک دوم ثبت می‌شود.',window:'روی دو سر دهانهٔ پنجره کلیک کنید؛ پس از کلیک دوم ثبت می‌شود.',passage:'روی دو سر مسیر باز کلیک کنید؛ پس از کلیک دوم ثبت می‌شود.'}};statusBox.textContent=msg[mode];render()}}
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
s.onwheel=e=>{{e.preventDefault();const p=svgPoint(e),f=e.deltaY>0?1.12:.88;view=[p.x+(view[0]-p.x)*f,p.y+(view[1]-p.y)*f,view[2]*f,view[3]*f];applyView();render()}};
s.onpointerdown=e=>{{if(mode==='pan'){{drag=[e.clientX,e.clientY,...view];s.setPointerCapture(e.pointerId)}}else{{const point=snap(e);if(['door','window','passage'].includes(mode)){{draft.push(point);if(draft.length===1){{statusBox.textContent='نقطهٔ اول ثبت شد؛ اکنون سر دیگر بازشو را انتخاب کنید.';render();return}}const kind=mode==='passage'?'open_passage':mode,a=draft[0],b=draft[1],mid=[(a[0]+b[0])/2,(a[1]+b[1])/2];golden.portals.push({{golden_portal_id:`PORTAL-${{String(golden.portals.length+1).padStart(3,'0')}}`,kind,status:'VERIFIED',point:mid,opening_segment:[a,b],space_a:null,space_b:null}});draft=[];save();statusBox.textContent=`${{kind==='door'?'در':kind==='window'?'پنجره':'مسیر باز'}} ثبت شد. تعداد بازشوها: ${{golden.portals.length}}`}}else{{draft.push(point);render()}}}}}};
s.onpointermove=e=>{{const p=sourcePoint(e);xy.textContent=`مختصات X: ${{p[0].toFixed(3)}} ، Y: ${{p[1].toFixed(3)}}`;if(drag){{view[0]=drag[2]-(e.clientX-drag[0])*view[2]/s.clientWidth;view[1]=drag[3]-(e.clientY-drag[1])*view[3]/s.clientHeight;applyView();render()}}}};s.onpointerup=()=>drag=null;
document.querySelector('#finish').onclick=()=>{{if(!['envelope','space','void'].includes(mode)){{statusBox.textContent='ابتدا یکی از ابزارهای محدوده یا فضا را انتخاب کنید.';return}}if(draft.length<3){{statusBox.textContent='حداقل سه گوشه لازم است.';return}}const ring=[...draft,draft[0]];if(mode==='envelope')golden.building_envelope={{status:'VERIFIED',outer_ring:ring,interior_voids:golden.building_envelope?.interior_voids||[]}};if(mode==='void')golden.building_envelope.interior_voids.push(ring);if(mode==='space'){{const id=`SPACE-${{String(golden.spaces.length+1).padStart(3,'0')}}`;golden.spaces.push({{golden_space_id:id,status:document.querySelector('#category').value==='UNKNOWN'?'UNKNOWN':'VERIFIED',polygon:ring,interior_rings:[],category:document.querySelector('#category').value,display_name:document.querySelector('#label').value||null,open_plan_group:null}})}}draft=[];save();statusBox.textContent='محدوده ثبت شد. می‌توانید مورد بعدی را رسم کنید.'}};
document.querySelector('#undo').onclick=()=>{{draft.pop();render()}};document.querySelector('#fit').onclick=()=>{{view=[...initial];applyView();render()}};
document.querySelector('#toggle-points').onclick=e=>{{const g=document.querySelector('#snap-points'),hidden=g.style.display==='none';g.style.display=hidden?'':'none';e.target.textContent=hidden?'پنهان‌کردن نقاط آبی':'نمایش نقاط آبی'}};
document.querySelector('#download').onclick=()=>{{golden.review.annotation_date=new Date().toISOString().slice(0,10);const blob=new Blob([JSON.stringify(golden,null,2)+'\\n'],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='{html.escape(case_id)}-golden-DRAFT.json';a.click();URL.revokeObjectURL(a.href)}};
document.querySelector('#import').onchange=async e=>{{try{{golden=JSON.parse(await e.target.files[0].text());save();statusBox.textContent='فایل قبلی با موفقیت باز شد.'}}catch{{statusBox.textContent='فایل انتخاب‌شده معتبر نیست.'}}}};
document.querySelector('#clear').onclick=()=>{{if(confirm('پیش‌نویس این پلان پاک شود؟')){{localStorage.removeItem(key);golden=JSON.parse(document.querySelector('#golden-seed').textContent);draft=[];render()}}}};render();
</script></html>'''


def _instructions(case_id,level,source_hash,frame_id,bounds):
    return f"""# Independent Golden review — {case_id}

Level: `{level}`

Source SHA-256: `{source_hash}`

Frame identity: `{frame_id}`

Frame bounds: `{bounds}`

Open `review.html`; it contains raw DXF primitives only. Do not open Planha
reconstruction output during annotation. The Persian step-by-step interface
provides explicit pan, envelope, space, void, door, window and open-passage
tools. It snaps clicks to nearby source vertices, saves drafts in the browser,
and downloads the Golden JSON; reviewers do not edit JSON manually.

1. Trace building outer ring and real courtyard/lightwell voids.
2. Trace every physical space. Furniture, cabinets, dimensions, annotations and
   stair-tread graphics are not physical spaces.
3. Use stable IDs (`SPACE-001`, ...); use `UNKNOWN` instead of guessing.
4. Add functional zones only when independently clear; do not invent boundaries.
5. Add DOOR, WINDOW and OPEN_PASSAGE independently with connected spaces or
   EXTERIOR. Unclear portals remain UNKNOWN.
6. Record geometric adjacency separately from portal access connectivity.
7. Annotator records name/date and changes DRAFT to REVIEWED.
8. A different reviewer validates the source, records review/approval dates and
   changes REVIEWED to APPROVED. Scoring is disabled before APPROVED.

Run the structural validator before review and approval. It never edits data.
"""


def build(source,case_id,level,bounds,runtime_frame_id):
    source=Path(source); data=source.read_bytes(); source_hash=sha256(data).hexdigest(); doc=ezdxf.readfile(source)
    svg,counts=_source_svg(doc,bounds,case_id)
    golden={"schema":"architectural-topology-golden/1.0","case_id":case_id,"source_sha256":source_hash,"review_status":"DRAFT",
            "review":{"method":"INDEPENDENT_SOURCE_ARCHITECTURE_REVIEW","annotator":None,"annotation_date":None,"reviewer":None,
                      "reviewed_at":None,"approved_at":None,"runtime_output_visible_during_annotation":False},
            "frame":{"runtime_frame_id":runtime_frame_id,"level":level,"bounds":bounds},"space_match_iou":.5,
            "building_envelope":{"status":"UNKNOWN","outer_ring":[],"interior_voids":[]},"spaces":[],"functional_zones":[],
            "portals":[],"geometric_adjacency":[],"access_connectivity":[],
            "annotation_notes":["Review source-only material without runtime output.","UNKNOWN is preferred to guessing."]}
    manifest={"case_id":case_id,"source_sha256":source_hash,"frame_identity":runtime_frame_id,"level":level,"bounds":bounds,
              "coordinate_system":"SOURCE_DXF_XY; SVG display uses -Y","render_source":"RAW_DXF_RECURSIVE_PRIMITIVES_ONLY",
              "rendered_primitive_counts":counts,"excluded_runtime_material":True}
    return svg,golden,manifest,_viewer(svg,case_id,level,bounds,golden),_instructions(case_id,level,source_hash,runtime_frame_id,bounds)


def main():
    p=argparse.ArgumentParser(); p.add_argument("--source",required=True); p.add_argument("--case-id",required=True); p.add_argument("--level",required=True)
    p.add_argument("--bounds",required=True,nargs=4,type=float); p.add_argument("--runtime-frame-id",required=True); p.add_argument("--output-dir",required=True)
    a=p.parse_args(); target=Path(a.output_dir); target.mkdir(parents=True,exist_ok=True)
    svg,golden,manifest,viewer,instructions=build(a.source,a.case_id,a.level,a.bounds,a.runtime_frame_id)
    for name,value in (("raw-source.svg",svg),("review.html",viewer),("REVIEWER-INSTRUCTIONS.md",instructions)): (target/name).write_text(value,encoding="utf-8")
    for name,value in (("golden.json",golden),("manifest.json",manifest)): (target/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"DRAFT_WAITING_FOR_INDEPENDENT_REVIEW","case_id":a.case_id,"package":str(target),"source_sha256":manifest["source_sha256"]},indent=2))


if __name__=="__main__": main()
