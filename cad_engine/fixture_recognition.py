"""Deterministic, provenance-preserving fixture/equipment recognition v2.

Object identity, plan context, hosting and engineering authority are independent.
The legacy ``detections`` projection contains only hosted, main-plan objects.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from hashlib import sha256
import json, re, time

SCHEMA="mep-object-recognition/2.0"; CANDIDATE_SCHEMA="mep-object-candidate/2.0"
FIXTURES={
 "wc":("wc","toilet","water closet","فرنگی"), "basin":("basin","lavatory","wash basin","روشویی"),
 "sink":("sink","kitchen sink","سینک"), "shower":("shower","دوش"),
 "floor_drain":("floor drain","floordrain","fd","کفشور"),
}
EQUIPMENT={
 "radiator":("radiator","رادیاتور"), "fan_coil":("fancoil","fan coil","fcu"),
 "split_indoor":("indoor split","split indoor","indoor unit"),
 "split_outdoor":("outdoor split","outdoor unit"), "exhaust_fan":("exhaust fan","exh fan"),
 "hood":("hood","هود"), "pump":("pump","پمپ"), "tank":("tank","مخزن"),
 "water_heater":("water heater","boiler","آبگرمکن"), "stove":("stove","range","اجاق"),
}
PORTS={
 "wc":["cold_water","sanitary","vent"], "basin":["cold_water","hot_water","sanitary","vent"],
 "sink":["cold_water","hot_water","sanitary","vent"], "shower":["cold_water","hot_water","sanitary","vent"],
 "floor_drain":["sanitary"], "radiator":["heating_supply","heating_return"],
 "fan_coil":["cooling_supply","cooling_return","condensate"],
 "split_indoor":["refrigerant_liquid","refrigerant_gas","condensate"],
 "split_outdoor":["refrigerant_liquid","refrigerant_gas"], "exhaust_fan":["exhaust"], "hood":["exhaust"],
 "pump":["cold_water"], "tank":["cold_water"], "water_heater":["cold_water","hot_water"], "stove":["gas"],
}

def _normal(value):
 value=str(value or "").replace("ي","ی").replace("ك","ک").replace("ۀ","ه").lower()
 return " ".join(re.findall(r"[\w\u0600-\u06ff]+",value.replace("_"," ").replace("-"," ").replace("."," ")))

def _exact_identity(value):
 normalized=_normal(value); tokens=set(normalized.split()); best=None
 for category,mapping in (("fixture",FIXTURES),("equipment",EQUIPMENT)):
  for kind,aliases in mapping.items():
   for alias in aliases:
    term=_normal(alias)
    if term and (normalized==term or set(term.split())<=tokens):
     candidate=(len(term),category,kind)
     if best is None or candidate[0]>best[0]: best=candidate
 return best[1:] if best else (None,None)

def _inside(point,polygon):
 if not point or not polygon:return False
 x,y=point; hit=False; j=len(polygon)-1
 for i,(xi,yi) in enumerate(polygon):
  xj,yj=polygon[j]
  if ((yi>y)!=(yj>y)) and x<(xj-xi)*(y-yi)/((yj-yi) or 1e-12)+xi:hit=not hit
  j=i
 return hit

def _stable(prefix,payload):
 raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
 return f"{prefix}-{sha256(raw.encode()).hexdigest()[:16].upper()}"

def _primitive_points(row):
 if row.get("point"):return [row["point"]]
 if row.get("start") and row.get("end"):return [row["start"],row["end"]]
 return row.get("points") or row.get("geometry") or []

def _signature(rows):
 kinds=Counter(r.get("entity_type") for r in rows if r.get("entity_type")!="INSERT")
 points=[p for row in rows for p in _primitive_points(row) if len(p)>=2]
 if not points:return None,None
 minx=min(float(p[0]) for p in points); maxx=max(float(p[0]) for p in points)
 miny=min(float(p[1]) for p in points); maxy=max(float(p[1]) for p in points)
 width,height=maxx-minx,maxy-miny; major=max(width,height,1e-12); minor=min(width,height)
 payload={"primitive_histogram":sorted(kinds.items()),"aspect_ratio":round(minor/major,4),
          "closed_paths":sum(bool(r.get("closed")) for r in rows),"point_count":len(points)}
 return sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),[minx,miny,maxx,maxy]

def _plan_context(point,frames):
 if not frames:return "MAIN_PLAN",None
 owners=[]
 for frame in frames:
  b=frame.get("bounds")
  if b and _inside(point,[(b[0],b[1]),(b[2],b[1]),(b[2],b[3]),(b[0],b[3])]):owners.append(frame)
 main=[f for f in owners if f.get("frame_type") in {"PRIMARY_FLOOR","ROOF","SITE"}]
 detail=[f for f in owners if f.get("frame_type") in {"DETAIL","LEGEND","SCHEDULE","SECTION","ELEVATION"}]
 if len(main)==1 and not detail:return "MAIN_PLAN",main[0].get("frame_id")
 if detail and not main:return "DETAIL_OR_LEGEND",detail[0].get("frame_id")
 if not owners:return "OUTSIDE_PLAN",None
 return "AMBIGUOUS_CONTEXT",None

def _hosting(point,rooms):
 room=next((r for r in rooms if _inside(point,r.get("polygon"))),None)
 if not room:return "UNHOSTED",None
 status=room.get("status")
 return ("HOSTED_PHYSICAL_SPACE" if status in {None,"VERIFIED","HIGH_CONFIDENCE"} else "HOSTED_CANDIDATE_SPACE"),room

def _legacy(row):
 return {"id":row["candidate_id"],"category":row["category_candidate"],"type":row["type_candidate"],
         "point":row["world_anchor"],"block":row.get("block_definition"),"layer":row.get("layer"),
         "room_id":row.get("host_id"),"room_type":row.get("host_type"),"ports":list(row.get("port_requirements") or []),
         "confidence":1.0,"evidence":list(row.get("evidence_families") or []),
         "installed":row["authority"]=="ENGINEERING_ELIGIBLE","recognition_status":row["recognition_status"],
         "hosting_status":row["hosting_status"],"plan_context":row["plan_context"],"authority":row["authority"]}

def recognize_fixtures_equipment(architecture):
 started=time.perf_counter(); rooms=[r for r in architecture.get("rooms") or [] if r.get("polygon")]
 frames=architecture.get("frames") or []; inserts=list(architecture.get("all_inserts") or [])
 by_root=defaultdict(list)
 for primitive in architecture.get("recognition_primitives") or []:
  root=primitive.get("root_insert_handle")
  if root:by_root[root].append(primitive)
 candidates=[]; signatures=defaultdict(list)
 for item in inserts:
  item_started=time.perf_counter(); category,kind=_exact_identity(item.get("name")); evidence=[]
  if kind:evidence.append("EXACT_BLOCK_IDENTITY")
  for attr in item.get("attributes") or []:
   ac,ak=_exact_identity(attr.get("text"))
   if ak and (not kind or (ac,ak)==(category,kind)):
    category,kind=ac,ak;evidence.append("EXACT_OBJECT_ATTRIBUTE")
  lc,lk=_exact_identity(item.get("layer"))
  if lk and (not kind or (lc,lk)==(category,kind)):
   category,kind=lc,lk;evidence.append("OBJECT_SPECIFIC_LAYER")
  root=item.get("root_insert_handle") or item.get("handle"); signature,bbox=_signature(by_root.get(root) or [])
  if signature:signatures[signature].append(len(candidates))
  point=item.get("point"); context,frame_id=_plan_context(point,frames); hosting,room=_hosting(point,rooms)
  representation=("ANONYMOUS_BLOCK" if str(item.get("name") or "").upper().startswith("*U") else
                  "NESTED_BLOCK" if item.get("nested_depth",0)>0 else "NAMED_BLOCK")
  status="DETERMINISTICALLY_CONFIRMED" if kind and evidence else "OBJECT_CANDIDATE"
  if context=="DETAIL_OR_LEGEND":status="REJECTED_NON_MEP"
  authority=("ENGINEERING_ELIGIBLE" if status=="DETERMINISTICALLY_CONFIRMED" and context=="MAIN_PLAN" and hosting=="HOSTED_PHYSICAL_SPACE" else
             "PREANALYSIS_EVIDENCE" if status=="DETERMINISTICALLY_CONFIRMED" and context=="MAIN_PLAN" else "INPUT_REQUIRED")
  row={"schema":CANDIDATE_SCHEMA,"candidate_id":_stable("MOC",[root,item.get("handle"),item.get("nested_path"),signature,point]),
       "source_representation":representation,"category_candidate":category,"type_candidate":kind,
       "world_anchor":point,"world_bbox":bbox,"source_handles":sorted({str(v) for v in (root,item.get("handle")) if v}),
       "root_insert_handle":root,"nested_path":list(item.get("nested_path") or []),
       "transform":{"rotation":item.get("rotation",0),"scale":item.get("scale",[1,1,1])},
       "layer":item.get("layer"),"block_definition":item.get("name"),"geometry_signature":signature,
       "text_evidence":[a.get("text") for a in item.get("attributes") or []],"object_layer_evidence":lk,
       "semantic_context":[],"plan_context":context,"frame_id":frame_id,"recognition_status":status,
       "hosting_status":hosting,"host_id":room.get("id") if room else None,"host_type":room.get("type") if room else None,
       "authority":authority,"uncertainties":[] if kind else ["NO_DETERMINISTIC_OBJECT_IDENTITY"],
       "evidence_families":sorted(set(evidence)),"port_requirements":list(PORTS.get(kind,[])),
       "connection_points":[],"classification_seconds":time.perf_counter()-item_started}
  candidates.append(row)
 # Exact object-specific primitive layers provide exploded-geometry evidence.
 # Bucketing is linear and scale-aware; it deliberately does not classify
 # unknown geometry merely because it resembles a remembered CAD symbol.
 frame_diagonals=[((f["bounds"][2]-f["bounds"][0])**2+(f["bounds"][3]-f["bounds"][1])**2)**.5
                  for f in frames if f.get("bounds")]
 cell=max(min(frame_diagonals or [200.0])*.005,1e-9)
 exploded=defaultdict(list)
 allowed={"LINE","ARC","CIRCLE","LWPOLYLINE","POLYLINE","ELLIPSE","SPLINE"}
 for primitive in architecture.get("recognition_primitives") or []:
  if primitive.get("root_insert_handle") or primitive.get("entity_type") not in allowed:continue
  category,kind=_exact_identity(primitive.get("layer"))
  points=_primitive_points(primitive)
  if not kind or not points:continue
  anchor=(sum(float(p[0]) for p in points)/len(points),sum(float(p[1]) for p in points)/len(points))
  exploded[(category,kind,round(anchor[0]/cell),round(anchor[1]/cell))].append((primitive,anchor))
 for (category,kind,_,_),members in exploded.items():
  rows=[m[0] for m in members]; points=[p for row in rows for p in _primitive_points(row)]
  anchor=(sum(float(p[0]) for p in points)/len(points),sum(float(p[1]) for p in points)/len(points))
  signature,bbox=_signature(rows); context,frame_id=_plan_context(anchor,frames); hosting,room=_hosting(anchor,rooms)
  status="REJECTED_NON_MEP" if context=="DETAIL_OR_LEGEND" else "DETERMINISTICALLY_CONFIRMED"
  authority=("ENGINEERING_ELIGIBLE" if status=="DETERMINISTICALLY_CONFIRMED" and context=="MAIN_PLAN" and hosting=="HOSTED_PHYSICAL_SPACE" else
             "PREANALYSIS_EVIDENCE" if status=="DETERMINISTICALLY_CONFIRMED" and context=="MAIN_PLAN" else "INPUT_REQUIRED")
  handles=sorted(str(r.get("handle")) for r in rows if r.get("handle"))
  candidates.append({"schema":CANDIDATE_SCHEMA,"candidate_id":_stable("MOC",["EXPLODED",handles,signature]),
   "source_representation":"EXPLODED_GEOMETRY","category_candidate":category,"type_candidate":kind,
   "world_anchor":anchor,"world_bbox":bbox,"source_handles":handles,"root_insert_handle":None,"nested_path":[],
   "transform":{"rotation":None,"scale":None},"layer":rows[0].get("layer"),"block_definition":None,
   "geometry_signature":signature,"text_evidence":[],"object_layer_evidence":kind,"semantic_context":[],
   "plan_context":context,"frame_id":frame_id,"recognition_status":status,"hosting_status":hosting,
   "host_id":room.get("id") if room else None,"host_type":room.get("type") if room else None,"authority":authority,
   "uncertainties":[],"evidence_families":["OBJECT_SPECIFIC_LAYER","SOURCE_GEOMETRY"],
   "port_requirements":list(PORTS.get(kind,[])),"connection_points":[],"classification_seconds":0.0})
 for signature,indexes in signatures.items():
  identities={(candidates[i]["category_candidate"],candidates[i]["type_candidate"]) for i in indexes
              if candidates[i]["recognition_status"]=="DETERMINISTICALLY_CONFIRMED"}
  if len(identities)!=1:continue
  category,kind=next(iter(identities))
  for index in indexes:
   row=candidates[index]
   if row["recognition_status"]!="OBJECT_CANDIDATE" or row["plan_context"]!="MAIN_PLAN":continue
   row.update(category_candidate=category,type_candidate=kind,recognition_status="DETERMINISTICALLY_CONFIRMED",
              authority="PREANALYSIS_EVIDENCE",port_requirements=list(PORTS.get(kind,[])))
   row["evidence_families"]=["LABELED_OR_NAMED_SIBLING","REPEATED_GEOMETRY_SIGNATURE"];row["uncertainties"]=[]
 deduped={}
 for row in candidates:
  key=(row.get("root_insert_handle") or row["candidate_id"],row.get("type_candidate")); previous=deduped.get(key)
  if previous is None or (previous["recognition_status"]!="DETERMINISTICALLY_CONFIRMED" and row["recognition_status"]=="DETERMINISTICALLY_CONFIRMED"):
   if previous:
    row["evidence_families"]=sorted(set(row["evidence_families"]+previous["evidence_families"]))
    row["source_handles"]=sorted(set(row["source_handles"]+previous["source_handles"]))
   deduped[key]=row
  else:
   previous["evidence_families"]=sorted(set(previous["evidence_families"]+row["evidence_families"]))
   previous["source_handles"]=sorted(set(previous["source_handles"]+row["source_handles"]))
 candidates=sorted(deduped.values(),key=lambda row:row["candidate_id"])
 confirmed=[r for r in candidates if r["recognition_status"]=="DETERMINISTICALLY_CONFIRMED"]
 ambiguous=[r for r in candidates if r["recognition_status"] in {"OBJECT_CANDIDATE","AMBIGUOUS"}]
 rejected=[r for r in candidates if r["recognition_status"]=="REJECTED_NON_MEP"]
 eligible=[_legacy(r) for r in confirmed if r["authority"]=="ENGINEERING_ELIGIBLE"]
 legacy_candidates=[_legacy(r) for r in candidates if r["authority"]!="ENGINEERING_ELIGIBLE"]
 return {"schema":SCHEMA,"version":SCHEMA,"object_candidates":candidates,"confirmed_objects":confirmed,
         "ambiguous_objects":ambiguous,"rejected_objects":rejected,
         "unhosted_confirmed":[r for r in confirmed if r["hosting_status"]=="UNHOSTED"],
         "detections":eligible,"candidates":legacy_candidates,
         "fixtures":[r for r in eligible if r["category"]=="fixture"],"equipment":[r for r in eligible if r["category"]=="equipment"],
         "quality":{"candidate_count":len(candidates),"confirmed_count":len(confirmed),"installed_detected":len(eligible),
                    "unassigned_candidates":len(legacy_candidates),"unhosted_confirmed":sum(r["hosting_status"]=="UNHOSTED" for r in confirmed),
                    "with_ports":sum(bool(r["ports"]) for r in eligible),"high_confidence":len(eligible),
                    "vision_created_fixture_count":0,"vision_created_equipment_count":0,
                    "vision_created_network_node_count":0,"vision_created_route_count":0,
                    "runtime_seconds":time.perf_counter()-started}}
