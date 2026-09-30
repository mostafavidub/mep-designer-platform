#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build source-only review material; never import reconstruction output."""
from __future__ import annotations
import argparse, html, json, sys
from hashlib import sha256
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
import ezdxf
from ezdxf.disassemble import recursive_decompose
from shapely.geometry import LineString, box
from shapely.ops import unary_union
from cad_engine.build_identity import build_identity
from tools.architectural_golden_review import export_proposals, new_golden


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
function portalMark(item){{const colors={{door:'#ea580c',window:'#16a34a',open_passage:'#db2777'}},color=colors[item.kind],segment=item.opening_segment||[],scale=Math.max(view[2],view[3]);if(segment.length===2){{const line=path(segment,false,color);line.style.strokeWidth='6px';line.setAttribute('stroke-linecap','round');segment.forEach(x=>dot(x,color))}}dot(item.point,color);const t=document.createElementNS(NS,'text');t.setAttribute('x',item.point[0]);t.setAttribute('y',-item.point[1]-scale*.012);t.setAttribute('fill',color);t.style.fill=color;t.setAttribute('font-size',scale*.018);t.setAttribute('font-weight','900');t.setAttribute('paint-order','stroke');t.setAttribute('stroke','#fff');t.setAttribute('stroke-width',scale*.004);t.textContent={{door:'در',window:'پنجره',open_passage:'مسیر باز'}}[item.kind];overlay.appendChild(t)}}
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


def _instructions_v2(case_id,level,source_hash,frame_id,bounds):
    return f"""# Golden Review v2 — {case_id}

Level: `{level}`
Source SHA-256: `{source_hash}`
Frame: `{frame_id}`
Bounds: `{bounds}`

Open `review.html` in a browser. It is self-contained and works offline.

1. In **بازبینی پیشنهادها**, select every orange proposal and mark it Correct,
   Wrong, Edited or Unsure. Orange is only a proposal; green is accepted Golden.
2. Drag blue vertices to edit geometry. Double-click an edge to add a vertex.
   Undo, redo and cancel remain available.
3. In **کنترل منبع**, enter source-only mode. All proposals and accepted overlays
   disappear. Inspect all nine sectors and answer all four omission questions.
   Add any missing space, void, door, window or open passage from the raw plan.
4. A different person uses **بازبین مستقل**. They first repeat the nine-sector
   source-only pass, then reveal the final overlay.
5. Approval stays disabled until every proposal, sector, question, identity,
   critical issue and geometry requirement is complete. Windows never create
   access connectivity. Official scoring is disabled until `APPROVED`.
6. Use **دانلود golden.json** to save progress. Browser autosave is local to this
   case and the JSON can be re-imported later.

Do not edit the JSON by hand. `UNSURE` is preferred to guessing. The package
contains the current baseline proposals only; it makes no DeepSeek call and no
new inference while you review it.
"""


def _reviewer_v2(svg,case_id,level,bounds,golden):
    initial=",".join(str(v) for v in (bounds[0],-bounds[3],bounds[2]-bounds[0],bounds[3]-bounds[1]))
    seed=json.dumps(golden,ensure_ascii=False).replace("</","<\\/")
    return f'''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Golden Review v2 — {html.escape(case_id)}</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;height:100%;font:13px system-ui;color:#152033;background:#e9eef5}}body{{display:grid;grid-template-rows:auto 1fr}}
header{{background:#0f172a;color:#fff;padding:9px 14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}}header b{{font-size:16px}}.badge{{padding:4px 9px;border-radius:999px;background:#334155}}.truth{{background:#065f46}}
#app{{display:grid;grid-template-columns:370px 1fr;min-height:0;direction:ltr}}aside{{direction:rtl;background:#fff;border-left:1px solid #cbd5e1;overflow:auto;padding:12px}}main{{position:relative;min-width:0;background:#cad3df}}
.tabs,.row,.actions{{display:flex;gap:6px;flex-wrap:wrap}}button,input,select,textarea{{font:inherit}}button{{border:1px solid #94a3b8;border-radius:8px;background:#fff;padding:7px 9px;cursor:pointer}}button:hover{{background:#f1f5f9}}button.active,.primary{{background:#2563eb;color:#fff;border-color:#1d4ed8}}button.good{{background:#059669;color:#fff}}button.bad{{background:#dc2626;color:#fff}}button.warn{{background:#d97706;color:#fff}}button:disabled{{opacity:.45;cursor:not-allowed}}
input,select,textarea{{width:100%;border:1px solid #cbd5e1;border-radius:7px;padding:7px}}textarea{{min-height:56px}}h2{{font-size:16px;margin:8px 0}}h3{{font-size:14px;margin:14px 0 6px}}p{{line-height:1.65;margin:5px 0;color:#475569}}.panel{{display:none}}.panel.active{{display:block}}.notice{{padding:9px;border-radius:8px;background:#eff6ff;border:1px solid #bfdbfe;margin:7px 0;line-height:1.55}}.critical{{background:#fff1f2;border-color:#fecdd3}}
#canvas{{position:absolute;inset:0;overflow:hidden}}svg{{width:100%;height:100%;background:#fff;touch-action:none}}#source-plan polyline{{stroke:#334155!important;stroke-width:1.05px!important}}#source-plan text{{fill:#111!important}}.overlay{{vector-effect:non-scaling-stroke;stroke-width:2px}}.proposal-space{{fill:#f59e0b22;stroke:#d97706}}.gold-space{{fill:#22c55e22;stroke:#15803d}}.wrong{{fill:#ef444422;stroke:#dc2626;stroke-dasharray:7 5}}.unsure{{fill:#a855f722;stroke:#7e22ce;stroke-dasharray:4 4}}.selected{{stroke:#2563eb!important;stroke-width:4px!important}}.vertex{{fill:#fff;stroke:#2563eb;stroke-width:2px;vector-effect:non-scaling-stroke;cursor:move}}.sector{{fill:none;stroke:#0ea5e9;stroke-width:1px;stroke-dasharray:5 5;vector-effect:non-scaling-stroke}}
.dimmed{{opacity:.12}}.space-number{{font-weight:900;fill:#7c2d12!important;paint-order:stroke;stroke:#fff;stroke-width:.08;pointer-events:none}}#focus-badge{{display:none;position:absolute;z-index:5;transform:translate(-50%,-130%);padding:3px 7px;border-radius:999px;background:#1d4ed8;color:#fff;border:2px solid #fff;box-shadow:0 1px 5px #0006;font-weight:800;font-size:13px;line-height:18px;white-space:nowrap;pointer-events:none}}#minimap{{position:absolute;direction:ltr;left:12px;top:12px;width:190px;height:135px;background:#fff;border:2px solid #334155;border-radius:9px;box-shadow:0 3px 12px #0004;overflow:hidden}}#minimap svg{{width:100%;height:100%}}#minimap polygon{{fill:#f59e0b22;stroke:#d97706;stroke-width:.08}}#minimap polygon.sel{{fill:#2563eb66;stroke:#1d4ed8;stroke-width:.18}}details{{margin:8px 0;border:1px solid #e2e8f0;border-radius:8px;padding:7px}}#evidence{{line-height:1.7;background:#f8fafc;border-radius:8px;padding:8px}}.question{{font-size:15px;font-weight:800;margin-top:12px}}#rejection-panel{{display:none;background:#fff7ed;border:1px solid #fdba74;border-radius:9px;padding:9px;margin-top:8px}}#rejection-panel button{{font-weight:700}}
.item{{padding:8px;border:1px solid #e2e8f0;border-radius:8px;margin:6px 0;cursor:pointer}}.item.sel{{border-color:#2563eb;background:#eff6ff}}.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-left:5px;background:#94a3b8}}.CORRECT{{background:#16a34a}}.WRONG{{background:#dc2626}}.EDITED{{background:#2563eb}}.UNSURE{{background:#9333ea}}
.progress{{height:9px;background:#e2e8f0;border-radius:99px;overflow:hidden}}.progress i{{display:block;height:100%;background:#16a34a}}.sectors{{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}}.sectors label{{border:1px solid #cbd5e1;border-radius:6px;padding:6px;text-align:center}}.sectors input{{width:auto}}#status{{position:absolute;left:12px;bottom:12px;background:#0f172ae8;color:#fff;border-radius:8px;padding:8px;max-width:520px}}
@media(max-width:900px){{#app{{grid-template-columns:1fr;grid-template-rows:50vh 1fr}}aside{{grid-row:2}}}}
</style><header data-source="RAW DXF ONLY"><b>Golden Review v2</b><span class="badge">{html.escape(case_id)}</span><span class="badge">{html.escape(level)}</span><span class="badge truth">پیشنهاد ≠ حقیقت</span><span id="head-progress"></span></header>
<div id="app"><aside><div class="tabs"><button data-tab="annotate" class="active">۱. بازبینی پیشنهادها</button><button data-tab="complete">۲. کنترل منبع</button><button data-tab="review">۳. بازبین مستقل</button></div>
<section id="annotate" class="panel active"><div class="notice"><b>قاعده:</b> هر شکل نارنجی فقط پیشنهاد موتور است. آن را «درست»، «غلط»، «ویرایش‌شده» یا «نامطمئن» کنید. هیچ پیشنهاد تأییدنشده‌ای Golden نیست.</div>
<div class="row"><select id="kind-filter"><option value="all">همهٔ موارد</option><option value="envelope">محدوده ساختمان</option><option value="space">فضاها</option><option value="portal">بازشوها</option></select><select id="state-filter"><option value="all">همهٔ وضعیت‌ها</option><option value="UNREVIEWED">بررسی‌نشده</option><option value="CORRECT">درست</option><option value="WRONG">غلط</option><option value="EDITED">ویرایش‌شده</option><option value="UNSURE">نامطمئن</option></select></div>
<div class="row"><select id="rejection-filter"><option value="all">همهٔ علت‌های رد</option><option value="COLUMN">ستون</option><option value="WALL_OR_WALL_MASS">دیوار / جرم دیوار</option><option value="FURNITURE">مبلمان</option><option value="GRID_OR_AXIS">آکس / شبکه</option><option value="ANNOTATION_OR_DIMENSION">نوشته / اندازه‌گذاری</option><option value="OTHER_NON_SPACE">سایر</option></select><span id="rejection-summary"></span></div>
<div class="row"><label><input id="show-numbers" type="checkbox" checked> شماره فضاها</label><label><input id="show-labels" type="checkbox" checked> متن‌های دقیق</label><label><input id="show-portals" type="checkbox" checked> بازشوها</label></div>
<h3>پیشرفت</h3><div class="progress"><i id="progress-bar"></i></div><p id="progress-text"></p><div id="items"></div>
<div id="editor"><h3>مورد انتخاب‌شده</h3><h2 id="selection">یک فضا را انتخاب کنید</h2><div id="evidence">با انتخاب هر فضا، همان محدوده روی پلان بزرگ‌نمایی می‌شود.</div><p class="question">آیا این محدوده واقعاً یک فضای فیزیکی صحیح است؟</p><div class="actions"><button data-decision="CORRECT" class="good">✓ درست</button><button data-decision="WRONG" class="bad">✕ اشتباه</button><button data-decision="EDITED" class="primary">✎ اصلاح مرز</button><button data-decision="UNSURE" class="warn">؟ مطمئن نیستم</button></div>
<div id="rejection-panel"><b>این محدوده اگر فضای فیزیکی نیست، چیست؟</b><div class="actions"><button data-rejection="COLUMN">ستون</button><button data-rejection="WALL_OR_WALL_MASS">دیوار</button><button data-rejection="STRUCTURAL_ELEMENT">عنصر سازه‌ای</button><button data-rejection="FURNITURE">مبلمان</button><button data-rejection="VEHICLE">خودرو</button><button data-rejection="GRID_OR_AXIS">آکس / شبکه</button><button data-rejection="ANNOTATION_OR_DIMENSION">نوشته / اندازه‌گذاری</button><button data-rejection="STAIR_GRAPHICS">ترسیمات پله</button><button data-rejection="FIXTURE_OR_EQUIPMENT_GRAPHICS">نماد تجهیز</button><button data-rejection="OTHER_NON_SPACE">سایر</button><button data-rejection="UNKNOWN_NON_SPACE">مطمئن نیستم</button></div><small>میانبر سریع ستون: کلید K</small></div>
<div id="semantic-review"><p class="question">کاربری این فضا چیست؟</p><select id="semantic-value"><option value="UNKNOWN">نامشخص — فقط مرز را بررسی می‌کنم</option><option value="living">پذیرایی / نشیمن</option><option value="dining">ناهارخوری</option><option value="kitchen">آشپزخانه</option><option value="bedroom">اتاق خواب</option><option value="toilet">توالت</option><option value="bathroom">حمام</option><option value="corridor">راهرو</option><option value="stair">راه‌پله</option><option value="shaft">شفت / داکت</option></select><p id="semantic-evidence"></p></div><label>یادداشت بازبینی</label><textarea id="note"></textarea>
<div class="row"><button id="previous">قبلی</button><button id="next">بعدی</button><button id="next-unreviewed" class="primary">بعدی بررسی‌نشده</button><button id="whole-view">بازگشت به نمای کل پلان</button></div>
<div id="portal-editor" style="display:none"><label>نوع بازشو</label><select id="portal-kind"><option value="door">در</option><option value="window">پنجره</option><option value="open_passage">بازشوی بدون در</option><option value="UNKNOWN">نامشخص</option></select><div class="row"><div><label>فضای A</label><select id="portal-a"></select></div><div><label>فضای B</label><select id="portal-b"></select></div></div></div>
<h3>ویرایش هندسه</h3><p>رأس آبی را بکشید؛ روی ضلع دوبارکلیک کنید تا رأس افزوده شود. سپس «ویرایش‌شده» را بزنید.</p><div class="row"><button id="undo">↶ بازگشت</button><button id="redo">↷ جلو</button><button id="delete-vertex">حذف رأس</button><button id="cancel-edit">لغو ویرایش</button></div></div></section>
<section id="complete" class="panel"><div class="notice"><b>حالت کنترل منبع خام:</b> همهٔ پیشنهادها و تأییدهای قبلی پنهان‌اند. هر ۹ بخش پلان را فقط از روی خطوط و نوشته‌های منبع بررسی کنید.</div><button id="source-only" class="primary">ورود به حالت منبع خام</button>
<h3>۹ بخش پلان</h3><div class="sectors" id="sectors"></div><h3>پرسش‌های اجباری</h3><label><input class="q" data-q="missing_spaces" type="checkbox"> هیچ فضای فیزیکی جا نیفتاده است</label><label><input class="q" data-q="missing_portals" type="checkbox"> هیچ در/پنجره/مسیر بازی جا نیفتاده است</label><label><input class="q" data-q="missing_voids" type="checkbox"> Void/نورگیر/حیاط‌خلوت کنترل شده است</label><label><input class="q" data-q="source_labels_checked" type="checkbox"> تمام برچسب‌های منبع کنترل شده‌اند</label>
<h3>افزودن مورد جاافتاده</h3><div class="row"><button data-draw="space">+ فضای جاافتاده</button><button data-draw="void">+ Void</button><button data-draw="door">+ در</button><button data-draw="window">+ پنجره</button><button data-draw="open_passage">+ مسیر باز</button></div><label>نوع/نام فضا</label><input id="new-category" value="UNKNOWN"><button id="finish-draw" class="good">بستن و ثبت ترسیم</button><p id="draw-help"></p><button id="complete-pass" class="good">ثبت پایان کنترل منبع خام</button></section>
<section id="review" class="panel"><div class="notice"><b>بازبینی مستقل:</b> نام بازبین باید با annotator متفاوت باشد. ابتدا منبع خام را بخش‌به‌بخش کنترل کنید؛ سپس overlay نهایی را ببینید.</div><label>نام annotator</label><input id="annotator"><label>نام بازبین مستقل</label><input id="reviewer"><button id="review-source" class="primary">کنترل مستقل منبع خام</button><div class="sectors" id="review-sectors"></div><button id="review-overlay">نمایش overlay نهایی</button><button id="review-complete" class="good">پایان بازبینی مستقل</button><h3>گیت تصویب</h3><div id="gate" class="notice critical"></div><button id="approve" class="good" disabled>APPROVE GOLDEN</button></section>
<hr><div class="row"><button id="fit">نمایش کامل</button><button id="export" class="primary">دانلود golden.json</button><button id="export-summary">دانلود خلاصه</button><label style="border:1px solid #94a3b8;border-radius:8px;padding:7px">بازکردن JSON<input id="import" type="file" accept="application/json" hidden></label></div></aside>
<main><div id="canvas">{svg}</div><div id="focus-badge"></div><div id="minimap"></div><div id="status">برای مشاهدهٔ دقیق، «فضای ۱، ۲، ...» را انتخاب کنید.</div></main></div>
<script id="golden-seed" type="application/json">{seed}</script><script>
const NS='http://www.w3.org/2000/svg',s=document.querySelector('#source-plan'),initial=[{initial}],storeKey='planha-golden-v2:{html.escape(case_id)}';let view=[...initial],drag=null,selected=null,selectedVertex=null,drawMode=null,draft=[],sourceOnly=false,history=[],future=[];
const seedG=JSON.parse(document.querySelector('#golden-seed').textContent),stored=localStorage.getItem(storeKey);let g=stored?JSON.parse(stored):seedG;if(stored){{for(const kind of ['spaces','portals']){{const old=new Map((g.proposals?.[kind]||[]).map(x=>[x.proposal_id,x]));g.proposals[kind]=seedG.proposals[kind].map(x=>Object.assign({{}},x,old.get(x.proposal_id)||{{}}))}}g.proposals.building_envelope=Object.assign({{}},seedG.proposals.building_envelope,g.proposals?.building_envelope||{{}});g.proposals.label_bindings=seedG.proposals.label_bindings;for(const key of ['schema_version','golden_id','project_reference'])if(!g[key])g[key]=seedG[key]}}const layer=document.createElementNS(NS,'g');layer.id='review-overlays';s.appendChild(layer);
const allProposals=()=>[{{kind:'envelope',row:g.proposals.building_envelope}},...g.proposals.spaces.map(row=>({{kind:'space',row}})),...g.proposals.portals.map(row=>({{kind:'portal',row}}))].filter(x=>x.row&&x.row.proposal_id);
function applyView(){{s.setAttribute('viewBox',view.join(' '))}}applyView();function pt(e){{let p=s.createSVGPoint();p.x=e.clientX;p.y=e.clientY;p=p.matrixTransform(s.getScreenCTM().inverse());return [p.x,-p.y]}}
function ringEl(points,klass,id){{if(!points?.length)return null;const el=document.createElementNS(NS,'polygon');el.setAttribute('points',points.map(p=>p[0]+','+(-p[1])).join(' '));el.setAttribute('class','overlay '+klass+(selected===id?' selected':''));el.dataset.id=id;layer.appendChild(el);return el}}
function lineEl(points,klass,id){{if(!points?.length)return null;const el=document.createElementNS(NS,'polyline');el.setAttribute('points',points.map(p=>p[0]+','+(-p[1])).join(' '));el.setAttribute('class','overlay '+klass+(selected===id?' selected':''));el.setAttribute('fill','none');el.dataset.id=id;layer.appendChild(el);return el}}
function boundedSvgLabelSize(){{const span=Math.max(view[2],view[3]);return Math.min(span*.035,Math.max(span*.018,span*.025))}}function numberEl(row){{if(!row.centroid||selected===row.proposal_id)return;const t=document.createElementNS(NS,'text');t.setAttribute('x',row.centroid[0]);t.setAttribute('y',-row.centroid[1]);t.setAttribute('text-anchor','middle');t.setAttribute('dominant-baseline','middle');t.setAttribute('font-size',boundedSvgLabelSize());t.setAttribute('class','space-number'+(selected?' dimmed':''));t.textContent=row.display_index;t.dataset.id=row.proposal_id;layer.appendChild(t)}}
function dispositionClass(d){{return d==='WRONG'?'wrong':d==='UNSURE'?'unsure':'proposal-space'}}
function render(){{layer.innerHTML='';if(!sourceOnly){{allProposals().forEach(x=>{{const dim=selected&&selected!==x.row.proposal_id?' dimmed':'';if(x.kind==='space'){{ringEl(x.row.polygon,dispositionClass(x.row.disposition)+dim,x.row.proposal_id);if(document.querySelector('#show-numbers').checked)numberEl(x.row)}}if(x.kind==='envelope')lineEl(x.row.outer_ring,dispositionClass(x.row.disposition)+dim,x.row.proposal_id);if(x.kind==='portal'&&document.querySelector('#show-portals').checked)lineEl(x.row.opening_segment,dispositionClass(x.row.disposition)+dim,x.row.proposal_id)}});g.spaces.forEach(x=>ringEl(x.polygon,'gold-space',x.golden_space_id));if(document.querySelector('#show-portals').checked)g.portals.forEach(x=>lineEl(x.opening_segment,'gold-space',x.golden_portal_id))}}drawSectors();if(draft.length)lineEl(draft,'selected','draft');renderVertices();renderList();renderMinimap();renderFocusBadge();updateGate();save()}}
function renderVertices(){{const item=allProposals().find(x=>x.row.proposal_id===selected);const points=item?.kind==='space'?item.row.polygon:item?.kind==='envelope'?item.row.outer_ring:null;if(!points||sourceOnly)return;points.slice(0,-1).forEach((p,i)=>{{const c=document.createElementNS(NS,'circle');c.setAttribute('cx',p[0]);c.setAttribute('cy',-p[1]);c.setAttribute('r',Math.max(view[2],view[3])*.006);c.setAttribute('class','vertex');c.dataset.vertex=i;layer.appendChild(c)}})}}
function drawSectors(){{if(!sourceOnly)return;const [x,y,w,h]=initial;for(let r=0;r<3;r++)for(let c=0;c<3;c++){{const q=document.createElementNS(NS,'rect');q.setAttribute('x',x+c*w/3);q.setAttribute('y',y+r*h/3);q.setAttribute('width',w/3);q.setAttribute('height',h/3);q.setAttribute('class','sector');layer.appendChild(q)}}}}
function stateFa(x){{return {{UNREVIEWED:'در انتظار بررسی',CORRECT:'درست',WRONG:'اشتباه',EDITED:'اصلاح‌شده',UNSURE:'نامطمئن'}}[x]||x}}function semanticFa(x){{return {{UNKNOWN:'نامشخص',living:'پذیرایی',reception:'پذیرایی',dining:'ناهارخوری',kitchen:'آشپزخانه',bedroom:'اتاق خواب',toilet:'توالت',bathroom:'حمام',corridor:'راهرو',stair:'راه‌پله',shaft:'شفت/داکت'}}[x]||x}}function rejectionFa(x){{return {{COLUMN:'ستون',WALL_OR_WALL_MASS:'دیوار / جرم دیوار',STRUCTURAL_ELEMENT:'عنصر سازه‌ای',FURNITURE:'مبلمان',VEHICLE:'خودرو',GRID_OR_AXIS:'آکس / شبکه',ANNOTATION_OR_DIMENSION:'نوشته / اندازه‌گذاری',STAIR_GRAPHICS:'ترسیمات پله',FIXTURE_OR_EQUIPMENT_GRAPHICS:'نماد تجهیز',OTHER_NON_SPACE:'سایر',UNKNOWN_NON_SPACE:'مطمئن نیستم'}}[x]||x}}
function rejectionCounts(){{return g.proposals.spaces.filter(x=>x.disposition==='WRONG'&&x.rejection_class).reduce((a,x)=>(a[x.rejection_class]=(a[x.rejection_class]||0)+1,a),{{}})}}function renderList(){{const k=document.querySelector('#kind-filter').value,st=document.querySelector('#state-filter').value,rf=document.querySelector('#rejection-filter').value,rows=allProposals(),done=rows.filter(x=>x.row.disposition!=='UNREVIEWED').length,counts=rejectionCounts();document.querySelector('#progress-bar').style.width=(rows.length?100*done/rows.length:100)+'%';document.querySelector('#progress-text').textContent=`${{done}} از ${{rows.length}} مورد بررسی شده`;document.querySelector('#head-progress').textContent=`پیشرفت: ${{done}}/${{rows.length}}`;document.querySelector('#rejection-summary').textContent=Object.entries(counts).map(([k,v])=>rejectionFa(k)+': '+v).join('، ');document.querySelector('#items').innerHTML=rows.filter(x=>(k==='all'||x.kind===k)&&(st==='all'||x.row.disposition===st)&&(rf==='all'||x.row.rejection_class===rf)).map(x=>`<div class="item ${{selected===x.row.proposal_id?'sel':''}}" data-pick="${{x.row.proposal_id}}"><i class="dot ${{x.row.disposition}}"></i><b>${{x.kind==='space'?x.row.display_name_fa:x.kind==='portal'?'بازشو':'محدوده ساختمان'}}</b><br><small>هندسه: ${{stateFa(x.row.disposition)}}${{x.row.rejection_class?' — '+rejectionFa(x.row.rejection_class):x.kind==='space'?' · کاربری: '+(x.row.category==='UNKNOWN'?'نامشخص':semanticFa(x.row.category)+' پیشنهادی'):''}}</small></div>`).join('');document.querySelectorAll('[data-pick]').forEach(el=>el.onclick=()=>select(el.dataset.pick))}}
function portalOptions(value){{return ['UNKNOWN','EXTERIOR',...g.spaces.map(x=>x.golden_space_id)].map(x=>`<option value="${{x}}" ${{x===value?'selected':''}}>${{x}}</option>`).join('')}}
function focusRing(p){{if(!p?.length)return;const xs=p.map(q=>q[0]),ys=p.map(q=>-q[1]),minx=Math.min(...xs),maxx=Math.max(...xs),miny=Math.min(...ys),maxy=Math.max(...ys),pad=Math.max(maxx-minx,maxy-miny,.5)*.45;view=[minx-pad,miny-pad,maxx-minx+2*pad,maxy-miny+2*pad];applyView()}}
function renderMinimap(){{const box=document.querySelector('#minimap');if(sourceOnly){{box.style.display='none';return}}box.style.display='block';const polys=g.proposals.spaces.map(r=>`<polygon class="${{selected===r.proposal_id?'sel':''}}" points="${{r.polygon.map(p=>p[0]+','+(-p[1])).join(' ')}}"/>`).join('');box.innerHTML=`<svg viewBox="${{initial.join(' ')}}">${{polys}}</svg>`}}
function renderFocusBadge(){{const badge=document.querySelector('#focus-badge'),row=g.proposals.spaces.find(x=>x.proposal_id===selected);if(sourceOnly||!row?.centroid||!document.querySelector('#show-numbers').checked){{badge.style.display='none';return}}const p=s.createSVGPoint();p.x=row.centroid[0];p.y=-row.centroid[1];const screen=p.matrixTransform(s.getScreenCTM()),rect=s.closest('main').getBoundingClientRect();badge.textContent=row.display_name_fa;badge.style.left=(screen.x-rect.left+10)+'px';badge.style.top=(screen.y-rect.top-6)+'px';badge.style.display='block'}}
function select(id,doFocus=true){{selected=id;document.querySelector('#rejection-panel').style.display='none';const x=allProposals().find(x=>x.row.proposal_id===id),space=x?.kind==='space'?x.row:null;document.querySelector('#selection').textContent=x?(space?space.display_name_fa:(x.kind==='portal'?'بازشو':'محدوده ساختمان')):'—';document.querySelector('#note').value=x?.row.review_note||'';if(space){{const inside=space.exact_labels_inside||[],near=space.exact_labels_near_boundary||[],hints=space.semantic_hints||[],hasSemantic=inside.length||hints.length||(space.category&&space.category!=='UNKNOWN'),labelText=inside.map(z=>'«'+z.text+'»').join('، ')||'ندارد';document.querySelector('#semantic-review').style.display=hasSemantic?'block':'none';document.querySelector('#evidence').innerHTML=`<b>هندسه:</b> ${{stateFa(space.disposition)}}<br><b>مساحت:</b> ${{space.area_drawing_units?.toFixed(2)||'نامشخص'}}<br><b>برچسب دقیق داخل:</b> ${{labelText}}<br><b>برچسب نزدیک مرز:</b> ${{near.map(z=>'«'+z.text+'»').join('، ')||'ندارد'}}<br><b>راهنمای کاربری:</b> ${{hasSemantic?semanticFa(space.category)+' پیشنهادی':'نامشخص — فعلاً فقط مرز را بررسی کنید'}}<br><b>بازشوهای مرتبط:</b> ${{space.touching_portal_candidate_ids.length}}<br><details><summary>جزئیات فنی</summary>${{space.source_id}}<br>${{space.boundary_evidence_summary}}<br>${{JSON.stringify(space.unresolved_issues||[])}}</details>`;document.querySelector('#semantic-evidence').textContent=inside.length?'شواهد: متن DXF '+labelText:hints.length?'شواهد معنایی موجود است.':'کاربری هنوز تعیین نشده — فعلاً فقط مرز فضا را بررسی کنید.';document.querySelector('#semantic-value').value=space.category||'UNKNOWN';if(doFocus)focusRing(space.polygon)}}else document.querySelector('#semantic-review').style.display='none';const pe=document.querySelector('#portal-editor');pe.style.display=x?.kind==='portal'?'block':'none';if(x?.kind==='portal'){{document.querySelector('#portal-kind').value=x.row.kind;document.querySelector('#portal-a').innerHTML=portalOptions(x.row.space_a||'UNKNOWN');document.querySelector('#portal-b').innerHTML=portalOptions(x.row.space_b||'UNKNOWN')}}render()}}
function snapshot(){{history.push(JSON.stringify(g));if(history.length>50)history.shift();future=[]}}function restore(raw){{g=JSON.parse(raw);render()}}function save(){{localStorage.setItem(storeKey,JSON.stringify(g))}}
function accepted(row,kind){{if(kind==='space'){{let hit=g.spaces.find(x=>x.proposal_id===row.proposal_id),value={{golden_space_id:hit?.golden_space_id||'SPACE-'+String(g.spaces.length+1).padStart(3,'0'),proposal_id:row.proposal_id,status:row.disposition==='UNSURE'?'UNKNOWN':'VERIFIED',polygon:structuredClone(row.polygon),interior_rings:structuredClone(row.interior_rings||[]),category:row.category||'UNKNOWN',display_name:row.display_name||null,open_plan_group:null}};if(hit)Object.assign(hit,value);else g.spaces.push(value)}}if(kind==='envelope')g.building_envelope={{status:row.disposition==='UNSURE'?'UNKNOWN':'VERIFIED',outer_ring:structuredClone(row.outer_ring),interior_voids:structuredClone(row.interior_voids||[])}};if(kind==='portal'){{let hit=g.portals.find(x=>x.proposal_id===row.proposal_id),value={{golden_portal_id:hit?.golden_portal_id||'PORTAL-'+String(g.portals.length+1).padStart(3,'0'),proposal_id:row.proposal_id,kind:row.kind,status:row.disposition==='UNSURE'?'UNKNOWN':'VERIFIED',point:row.point,opening_segment:structuredClone(row.opening_segment||[]),space_a:row.space_a,space_b:row.space_b}};if(hit)Object.assign(hit,value);else g.portals.push(value)}}}}
function finalizeDecision(decision,rejectionClass=null){{const x=allProposals().find(x=>x.row.proposal_id===selected);if(!x)return;snapshot();if(x.kind==='portal'){{x.row.kind=document.querySelector('#portal-kind').value;x.row.space_a=document.querySelector('#portal-a').value;x.row.space_b=document.querySelector('#portal-b').value}}x.row.disposition=decision;x.row.rejection_class=decision==='WRONG'&&x.kind==='space'?rejectionClass:null;x.row.review_note=document.querySelector('#note').value;x.row.final_geometry=x.kind==='space'?structuredClone(x.row.polygon):x.kind==='envelope'?structuredClone(x.row.outer_ring):structuredClone(x.row.opening_segment||[]);x.row.annotation_timestamp=new Date().toISOString();if(decision==='WRONG'){{g.spaces=g.spaces.filter(y=>y.proposal_id!==selected);g.portals=g.portals.filter(y=>y.proposal_id!==selected);const audit={{proposal_id:x.row.proposal_id,source_candidate_id:x.row.source_candidate_id,original_geometry:structuredClone(x.row.original_geometry),disposition:'WRONG',rejection_class:x.row.rejection_class,review_note:x.row.review_note,annotator:g.review.annotator,timestamp:x.row.annotation_timestamp}};g.rejected_proposals=g.rejected_proposals.filter(y=>(typeof y==='string'?y:y.proposal_id)!==selected);g.rejected_proposals.push(audit)}}else accepted(x.row,x.kind);g.proposal_review_log.push({{proposal_id:selected,disposition:decision,rejection_class:x.row.rejection_class,note:x.row.review_note,at:x.row.annotation_timestamp}});document.querySelector('#rejection-panel').style.display='none';if(allProposals().every(x=>x.row.disposition!=='UNREVIEWED'))g.review_status=g.annotation_status='ASSISTED_REVIEW_COMPLETE';render()}}
document.querySelectorAll('[data-decision]').forEach(b=>b.onclick=()=>{{const x=allProposals().find(x=>x.row.proposal_id===selected);if(!x)return;if(b.dataset.decision==='WRONG'&&x.kind==='space'){{document.querySelector('#rejection-panel').style.display='block';return}}finalizeDecision(b.dataset.decision)}});document.querySelectorAll('[data-rejection]').forEach(b=>b.onclick=()=>{{finalizeDecision('WRONG',b.dataset.rejection);document.querySelector('#next-unreviewed').click()}});
function spaceRows(){{return g.proposals.spaces}}function stepSpace(delta){{const rows=spaceRows(),i=rows.findIndex(x=>x.proposal_id===selected);if(rows.length)select(rows[(Math.max(i,0)+delta+rows.length)%rows.length].proposal_id)}}document.querySelector('#previous').onclick=()=>stepSpace(-1);document.querySelector('#next').onclick=()=>stepSpace(1);document.querySelector('#next-unreviewed').onclick=()=>{{const rows=spaceRows(),i=rows.findIndex(x=>x.proposal_id===selected),n=[...rows.slice(i+1),...rows.slice(0,i+1)].find(x=>x.disposition==='UNREVIEWED');if(n)select(n.proposal_id)}};document.querySelector('#whole-view').onclick=()=>{{view=[...initial];applyView();render()}};document.querySelector('#semantic-value').onchange=e=>{{const x=g.proposals.spaces.find(x=>x.proposal_id===selected);if(x){{x.category=e.target.value;x.semantic_human_decision={{value:e.target.value,at:new Date().toISOString()}};save()}}}};
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('[data-tab],.panel').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelector('#'+b.dataset.tab).classList.add('active')}});document.querySelectorAll('#kind-filter,#state-filter,#rejection-filter').forEach(x=>x.onchange=renderList);
document.querySelectorAll('#show-numbers,#show-portals').forEach(x=>x.onchange=render);document.querySelector('#show-labels').onchange=e=>s.querySelectorAll(':scope > text').forEach(x=>x.style.display=e.target.checked?'':'none');
s.onwheel=e=>{{e.preventDefault();const p=pt(e),q=[p[0],-p[1]],f=e.deltaY>0?1.12:.88;view=[q[0]+(view[0]-q[0])*f,q[1]+(view[1]-q[1])*f,view[2]*f,view[3]*f];applyView();render()}};
s.onpointerdown=e=>{{const vertex=e.target.dataset.vertex;if(vertex!==undefined){{snapshot();selectedVertex=Number(vertex);drag='vertex';return}}if(drawMode){{draft.push(pt(e));render();return}}const id=e.target.dataset.id;if(id&&id!=='draft'){{select(id);return}}drag=[e.clientX,e.clientY,...view];s.setPointerCapture(e.pointerId)}};
s.onpointermove=e=>{{if(drag==='vertex'){{const x=allProposals().find(x=>x.row.proposal_id===selected),points=x?.kind==='space'?x.row.polygon:x?.kind==='envelope'?x.row.outer_ring:null;if(points){{points[selectedVertex]=pt(e);points[points.length-1]=points[0];render()}}}}else if(Array.isArray(drag)){{view[0]=drag[2]-(e.clientX-drag[0])*view[2]/s.clientWidth;view[1]=drag[3]-(e.clientY-drag[1])*view[3]/s.clientHeight;applyView();render()}}}};s.onpointerup=()=>{{drag=null;selectedVertex=null}};
s.ondblclick=e=>{{const x=allProposals().find(x=>x.row.proposal_id===selected),points=x?.kind==='space'?x.row.polygon:x?.kind==='envelope'?x.row.outer_ring:null;if(!points)return;snapshot();points.splice(points.length-1,0,pt(e));points[points.length-1]=points[0];render()}};
document.querySelector('#undo').onclick=()=>{{if(history.length){{future.push(JSON.stringify(g));restore(history.pop())}}}};document.querySelector('#redo').onclick=()=>{{if(future.length){{history.push(JSON.stringify(g));restore(future.pop())}}}};document.querySelector('#cancel-edit').onclick=()=>document.querySelector('#undo').click();document.querySelector('#delete-vertex').onclick=()=>{{const x=allProposals().find(x=>x.row.proposal_id===selected),p=x?.kind==='space'?x.row.polygon:x?.kind==='envelope'?x.row.outer_ring:null;if(p&&p.length>4){{snapshot();p.splice(p.length-2,1);p[p.length-1]=p[0];render()}}}};
for(const target of ['sectors','review-sectors']){{const obj=target==='sectors'?g.completeness:g.reviewer_completeness;document.querySelector('#'+target).innerHTML=Object.keys(obj.sectors).map(k=>`<label>${{k}} <input type="checkbox" data-sector="${{k}}" ${{obj.sectors[k]?'checked':''}}></label>`).join('');document.querySelectorAll('#'+target+' [data-sector]').forEach(x=>x.onchange=()=>{{obj.sectors[x.dataset.sector]=x.checked;render()}})}}
document.querySelectorAll('.q').forEach(x=>x.onchange=()=>{{g.completeness.questions[x.dataset.q]=x.checked?false:null;render()}});document.querySelector('#source-only').onclick=()=>{{sourceOnly=true;selected=null;render()}};document.querySelector('#review-source').onclick=()=>{{sourceOnly=true;render()}};document.querySelector('#review-overlay').onclick=()=>{{sourceOnly=false;render()}};
document.querySelectorAll('[data-draw]').forEach(x=>x.onclick=()=>{{drawMode=x.dataset.draw;draft=[];document.querySelector('#draw-help').textContent='روی نقاط پلان کلیک کنید؛ برای ثبت فضای بسته حداقل سه نقطه لازم است.'}});document.querySelector('#finish-draw').onclick=()=>{{if(!drawMode||draft.length<(drawMode==='space'||drawMode==='void'?3:2))return;snapshot();let id;if(drawMode==='space'){{const ring=[...draft,draft[0]];id='SPACE-'+String(g.spaces.length+1).padStart(3,'0');g.spaces.push({{golden_space_id:id,status:'VERIFIED',polygon:ring,interior_rings:[],category:document.querySelector('#new-category').value||'UNKNOWN',display_name:null,open_plan_group:null,origin:'HUMAN_ADDED'}})}}else if(drawMode==='void'){{const ring=[...draft,draft[0]];id='VOID-'+String(g.building_envelope.interior_voids.length+1).padStart(3,'0');g.building_envelope.interior_voids.push(ring)}}else{{const a=draft[0],b=draft[1];id='PORTAL-'+String(g.portals.length+1).padStart(3,'0');g.portals.push({{golden_portal_id:id,kind:drawMode,status:'VERIFIED',point:[(a[0]+b[0])/2,(a[1]+b[1])/2],opening_segment:[a,b],space_a:'UNKNOWN',space_b:'UNKNOWN',origin:'HUMAN_ADDED'}})}}g.human_added_items.push(id);drawMode=null;draft=[];render()}};
document.querySelector('#complete-pass').onclick=()=>{{g.completeness.mode_completed=Object.values(g.completeness.sectors).every(Boolean)&&Object.values(g.completeness.questions).every(x=>x===false);if(g.completeness.mode_completed)g.review_status=g.annotation_status='COMPLETENESS_REVIEW_COMPLETE';sourceOnly=false;render()}};document.querySelector('#review-complete').onclick=()=>{{g.reviewer_completeness.completed=Object.values(g.reviewer_completeness.sectors).every(Boolean);sourceOnly=false;render()}};
function invalidRing(p){{if(!p||p.length<4)return true;let a=0,o=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);for(let i=0;i<p.length-1;i++)a+=p[i][0]*p[i+1][1]-p[i+1][0]*p[i][1];if(Math.abs(a)<1e-9)return true;for(let i=0;i<p.length-1;i++)for(let j=i+2;j<p.length-1;j++)if(!(i===0&&j===p.length-2)&&o(p[i],p[i+1],p[j])*o(p[i],p[i+1],p[j+1])<0&&o(p[j],p[j+1],p[i])*o(p[j],p[j+1],p[i+1])<0)return true;return p.some(q=>q[0]<initial[0]||q[0]>initial[0]+initial[2]||-q[1]<initial[1]||-q[1]>initial[1]+initial[3])}}
function gateErrors(){{let e=[];g.review.annotator=document.querySelector('#annotator').value.trim()||null;g.review.reviewer=document.querySelector('#reviewer').value.trim()||null;if(!g.review.annotator)e.push('نام annotator وارد نشده');if(!g.review.reviewer)e.push('نام بازبین وارد نشده');if(g.review.annotator&&g.review.annotator===g.review.reviewer)e.push('بازبین باید شخص دیگری باشد');if(allProposals().some(x=>x.row.disposition==='UNREVIEWED'))e.push('همه پیشنهادها بررسی نشده‌اند');if(!g.completeness.mode_completed)e.push('کنترل منبع خام کامل نیست');if(!g.reviewer_completeness.completed)e.push('بازبینی مستقل کامل نیست');if(!g.spaces.length)e.push('هیچ فضای Golden وجود ندارد');if(invalidRing(g.building_envelope.outer_ring)||g.spaces.some(x=>invalidRing(x.polygon)))e.push('هندسه نامعتبر یا خارج از قاب است');const ids=new Set(g.spaces.map(x=>x.golden_space_id)),ok=x=>!x||['UNKNOWN','EXTERIOR'].includes(x)||ids.has(x);if(g.portals.some(p=>!ok(p.space_a)||!ok(p.space_b)))e.push('اتصال بازشو نامعتبر است');return e}}
function recalcTopology(){{const key=p=>p.map(v=>Number(v).toFixed(6)).join(','),segments=x=>x.polygon.slice(1).map((p,i)=>[key(x.polygon[i]),key(p)].sort().join('|'));g.geometric_adjacency=[];for(let i=0;i<g.spaces.length;i++)for(let j=i+1;j<g.spaces.length;j++)if(segments(g.spaces[i]).some(e=>segments(g.spaces[j]).includes(e)))g.geometric_adjacency.push([g.spaces[i].golden_space_id,g.spaces[j].golden_space_id]);g.access_connectivity=g.portals.filter(p=>p.status==='VERIFIED'&&['door','open_passage'].includes(p.kind)&&p.space_a&&p.space_b&&p.space_a!==p.space_b).map(p=>({{space_a:p.space_a,space_b:p.space_b,portal_id:p.golden_portal_id}}))}}
function updateGate(){{const e=gateErrors(),box=document.querySelector('#gate');g.approval_gate={{eligible:!e.length,errors:e}};box.innerHTML=e.length?'قابل تصویب نیست:<br>• '+e.join('<br>• '):'تمام گیت‌ها پاس شده‌اند.';document.querySelector('#approve').disabled=!!e.length}}
document.querySelectorAll('#annotator,#reviewer').forEach(x=>x.oninput=updateGate);document.querySelector('#approve').onclick=()=>{{const e=gateErrors();if(e.length)return;const now=new Date().toISOString();recalcTopology();g.review_status=g.annotation_status='APPROVED';g.review.annotation_date=now.slice(0,10);g.review.reviewed_at=now;g.review.approved_at=now;g.review.independent_source_only_pass_completed=true;g.approval={{approved:true,reviewer:g.review.reviewer,at:now}};render()}};
function download(name,text,type='text/plain'){{const blob=new Blob([text],{{type}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();URL.revokeObjectURL(a.href)}}document.querySelector('#fit').onclick=()=>{{view=[...initial];applyView();render()}};document.querySelector('#export').onclick=()=>{{recalcTopology();download('{html.escape(case_id)}-golden-'+g.review_status+'.json',JSON.stringify(g,null,2)+'\\n','application/json')}};document.querySelector('#export-summary').onclick=()=>{{const rows=allProposals(),count=d=>rows.filter(x=>x.row.disposition===d).length,text=`خلاصه {html.escape(case_id)}\\nوضعیت: ${{g.review_status}}\\nپیشنهاد فضا: ${{g.proposals.spaces.length}}\\nتأیید: ${{count('CORRECT')}}\\nویرایش: ${{count('EDITED')}}\\nرد: ${{count('WRONG')}}\\nافزوده انسانی: ${{g.human_added_items.length}}\\nنامطمئن: ${{count('UNSURE')}}\\nبخش‌های کنترل‌شده: ${{Object.values(g.completeness.sectors).filter(Boolean).length}}/9\\n`;download('{html.escape(case_id)}-review-summary.txt',text)}};document.querySelector('#import').onchange=async e=>{{try{{g=JSON.parse(await e.target.files[0].text());render()}}catch{{alert('JSON معتبر نیست')}}}};document.onkeydown=e=>{{if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName))return;const key=e.key.toLowerCase(),map={{c:'CORRECT',w:'WRONG',e:'EDITED',u:'UNSURE'}};if(key==='k'&&document.querySelector('#rejection-panel').style.display==='block')document.querySelector('[data-rejection="COLUMN"]').click();else if(map[key])document.querySelector(`[data-decision="${{map[key]}}"]`).click();if(key==='n'){{const n=allProposals().find(x=>x.row.disposition==='UNREVIEWED');if(n)select(n.row.proposal_id)}}}};render();
</script></html>'''


def build(source,case_id,level,bounds,runtime_frame_id,proposal_model=None):
    source=Path(source); data=source.read_bytes(); source_hash=sha256(data).hexdigest(); doc=ezdxf.readfile(source)
    svg,counts=_source_svg(doc,bounds,case_id)
    proposals=export_proposals(proposal_model,runtime_frame_id) if proposal_model else None
    identity=build_identity()
    golden=new_golden(case_id=case_id,source_sha256=source_hash,frame_id=runtime_frame_id,
                      level=level,bounds=bounds,proposals=proposals,build=identity)
    manifest={"case_id":case_id,"source_sha256":source_hash,"frame_identity":runtime_frame_id,"level":level,"bounds":bounds,
              "coordinate_system":"SOURCE_DXF_XY; SVG display uses -Y","render_source":"RAW_DXF_RECURSIVE_PRIMITIVES_ONLY",
              "rendered_primitive_counts":counts,"excluded_runtime_material":proposal_model is None,
              "proposal_authority":"REVIEW_INPUT_ONLY" if proposal_model else "NONE",
              "proposal_counts":(proposals or {}).get("proposal_counts",{}),"build":identity}
    viewer=_reviewer_v2(svg,case_id,level,bounds,golden) if proposal_model else _viewer(svg,case_id,level,bounds,golden)
    instructions=(_instructions_v2 if proposal_model else _instructions)(case_id,level,source_hash,runtime_frame_id,bounds)
    return svg,golden,manifest,viewer,instructions


def main():
    p=argparse.ArgumentParser(); p.add_argument("--source",required=True); p.add_argument("--case-id",required=True); p.add_argument("--level",required=True)
    p.add_argument("--bounds",required=True,nargs=4,type=float); p.add_argument("--runtime-frame-id",required=True); p.add_argument("--output-dir",required=True)
    p.add_argument("--proposal-model",help="Existing canonical model JSON; exported read-only without inference")
    a=p.parse_args(); target=Path(a.output_dir); target.mkdir(parents=True,exist_ok=True)
    proposal_model=json.loads(Path(a.proposal_model).read_text(encoding="utf-8")) if a.proposal_model else None
    svg,golden,manifest,viewer,instructions=build(a.source,a.case_id,a.level,a.bounds,a.runtime_frame_id,proposal_model)
    for name,value in (("raw-source.svg",svg),("review.html",viewer),("REVIEWER-INSTRUCTIONS.md",instructions)): (target/name).write_text(value,encoding="utf-8")
    for name,value in (("golden.json",golden),("manifest.json",manifest)): (target/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"DRAFT_WAITING_FOR_INDEPENDENT_REVIEW","case_id":a.case_id,"package":str(target),"source_sha256":manifest["source_sha256"]},indent=2))


if __name__=="__main__": main()
