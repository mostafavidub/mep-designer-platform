from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import (
    ArchitecturalModel, ElectricalDesignBasis, ElectricalProjectModel,
    EngineeringStatus, EquipmentPlacement, EquipmentRequirement, EvidenceValue,
)


def _final(ev: EvidenceValue) -> bool:
    return ev.status == EngineeringStatus.FINAL and ev.value is not None


def _room(project, room_id):
    return next((r for r in project.rooms if r.id == room_id), None)


def _centroid(poly: Sequence[Tuple[float, float]]):
    if not poly:
        return None
    area2 = sum(poly[i][0]*poly[(i+1)%len(poly)][1] - poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly)))
    if abs(area2) < 1e-12:
        return sum(x for x,_ in poly)/len(poly), sum(y for _,y in poly)/len(poly)
    cx = sum((poly[i][0]+poly[(i+1)%len(poly)][0])*(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1]) for i in range(len(poly))) / (3*area2)
    cy = sum((poly[i][1]+poly[(i+1)%len(poly)][1])*(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1]) for i in range(len(poly))) / (3*area2)
    return float(cx), float(cy)


def _dist_point_segment(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx-ax, by-ay
    if dx*dx+dy*dy <= 1e-12:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy)))
    q = ax+t*dx, ay+t*dy
    return math.dist(p, q)


def _nearest_line(point, architecture: ArchitecturalModel, frame_id: Optional[str]):
    candidates = [e for e in architecture.entities if e.kind == "line_candidate" and (not frame_id or e.frame_id == frame_id)]
    return min(candidates, key=lambda e: _dist_point_segment(point, tuple(e.geometry["a"]), tuple(e.geometry["b"]))) if candidates else None


def _grid_points(poly, count):
    if not poly or count <= 0:
        return []
    if count == 1:
        return [_centroid(poly)]
    xs=[p[0] for p in poly]; ys=[p[1] for p in poly]
    x1,x2=min(xs),max(xs); y1,y2=min(ys),max(ys)
    aspect=(x2-x1 or 1)/(y2-y1 or 1)
    cols=max(1,math.ceil(math.sqrt(count*aspect))); rows=max(1,math.ceil(count/cols)); out=[]
    for r in range(rows):
        for c in range(cols):
            if len(out) >= count: break
            out.append((x1+(c+1)*(x2-x1)/(cols+1), y1+(r+1)*(y2-y1)/(rows+1)))
    return out


def resolve_quantities(requirements: List[EquipmentRequirement], project: ElectricalProjectModel,
                       basis: ElectricalDesignBasis, manufacturer_data: Optional[Dict[str,Any]]=None) -> List[EquipmentRequirement]:
    """Resolve only quantities supported by supplied evidence.

    Lighting fixture count uses the lumen method when room area, target lux,
    luminaire lumens, utilization factor and maintenance factor are all known.
    """
    manufacturer_data=manufacturer_data or {}
    lighting=basis.get("lighting_basis"); socket_rules=basis.get("socket_power_requirements"); appliances=basis.get("dedicated_appliance_requirements")
    for req in requirements:
        room=_room(project,req.room_id)
        if not room: continue
        kind=str(room.room_type.value or "unknown")
        if req.equipment_type=="LIGHT_FIXTURE":
            fixture=manufacturer_data.get("luminaires",{}).get(kind) or manufacturer_data.get("luminaires",{}).get("default")
            cfg=lighting.value if _final(lighting) and isinstance(lighting.value,dict) else {}
            target=cfg.get(kind) or cfg.get("default")
            if _final(room.area_m2) and isinstance(fixture,dict) and isinstance(target,(int,float)):
                lumens=fixture.get("lumens"); cu=fixture.get("utilization_factor"); mf=fixture.get("maintenance_factor")
                if all(isinstance(v,(int,float)) and v>0 for v in (target,lumens,cu,mf)):
                    count=max(1,math.ceil(float(target)*float(room.area_m2.value)/(float(lumens)*float(cu)*float(mf))))
                    req.quantity=EvidenceValue.final(count,"engineering_calculation",.95,"lumen_method")
                    if isinstance(fixture.get("input_power_w"),(int,float)):
                        req.load_w=EvidenceValue.final(float(fixture["input_power_w"]),"manufacturer_data",1.0)
                    continue
            req.quantity=EvidenceValue.input_required("room area + target lux + luminaire lumens/CU/MF required")
        elif req.equipment_type=="GENERAL_SOCKET":
            cfg=socket_rules.value if _final(socket_rules) and isinstance(socket_rules.value,dict) else {}
            rcfg=cfg.get(kind) or cfg.get("default")
            if isinstance(rcfg,dict) and isinstance(rcfg.get("minimum_count"),int) and rcfg["minimum_count"]>=0:
                req.quantity=EvidenceValue.final(rcfg["minimum_count"],"applicable_rule",1.0,str(rcfg.get("reference") or "project_socket_rule"))
                if isinstance(rcfg.get("design_load_w_per_outlet"),(int,float)):
                    req.load_w=EvidenceValue.final(float(rcfg["design_load_w_per_outlet"]),"applicable_rule",1.0)
            else:
                req.quantity=EvidenceValue.input_required(f"socket rule for {kind} required")
        elif req.equipment_type=="DEDICATED_APPLIANCE_OUTLET":
            cfg=appliances.value if _final(appliances) and isinstance(appliances.value,dict) else {}
            items=cfg.get(kind)
            if isinstance(items,list):
                req.quantity=EvidenceValue.final(len(items),"project_design_basis",1.0)
                req.basis.append("dedicated_appliance_requirements")
            else:
                req.quantity=EvidenceValue.input_required("dedicated appliance schedule required")
    return requirements


def place_equipment(requirements: List[EquipmentRequirement], project: ElectricalProjectModel,
                    architecture: ArchitecturalModel, placement_rules: Optional[Dict[str,Any]]=None) -> List[EquipmentPlacement]:
    placement_rules=placement_rules or {}; out=[]
    for req in requirements:
        room=_room(project,req.room_id)
        if not room or not isinstance(req.quantity.value,int) or req.quantity.value<=0: continue
        count=int(req.quantity.value); frame=room.frame_id
        if req.equipment_type=="LIGHT_FIXTURE" and room.polygon:
            for i,p in enumerate(_grid_points(room.polygon,count),1):
                out.append(EquipmentPlacement(req.id,f"EQ-{req.id}-{i}",req.level_id,frame,p,0.0,"ceiling",f"CEILING-{room.id}",room.id,
                                              EngineeringStatus.PRELIMINARY,{"room_ownership":room.id,"inside_room_layout":True}))
        elif req.equipment_type=="LIGHT_SWITCH":
            anchor=room.label_point or (_centroid(room.polygon) if room.polygon else None)
            doors=[e for e in architecture.entities if e.kind=="door" and e.frame_id==frame]
            if not anchor or not doors: continue
            door=min(doors,key=lambda e:math.dist(anchor,tuple(e.geometry["point"])))
            dp=tuple(door.geometry["point"]); wall=_nearest_line(dp,architecture,frame)
            if not wall: continue
            a=tuple(wall.geometry["a"]); b=tuple(wall.geometry["b"])
            angle=math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))
            qa={"distance_to_host":_dist_point_segment(dp,a,b),"door_relation":door.id,"orientation_deg":angle,"room_ownership":room.id}
            out.append(EquipmentPlacement(req.id,f"EQ-{req.id}-1",req.level_id,frame,dp,angle,"wall",wall.id,room.id,EngineeringStatus.PRELIMINARY,qa))
        elif req.equipment_type in {"GENERAL_SOCKET","DEDICATED_APPLIANCE_OUTLET"} and room.polygon:
            segments=[(a,room.polygon[(i+1)%len(room.polygon)]) for i,a in enumerate(room.polygon)]
            segments=[x for x in segments if math.dist(*x)>1e-9]
            segments.sort(key=lambda x:math.dist(*x),reverse=True)
            for i in range(count):
                if not segments: break
                a,b=segments[i%len(segments)]; p=((a[0]+b[0])/2,(a[1]+b[1])/2); angle=math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))
                out.append(EquipmentPlacement(req.id,f"EQ-{req.id}-{i+1}",req.level_id,frame,p,angle,"wall",f"ROOMSEG-{room.id}-{i%len(segments)}",room.id,
                                              EngineeringStatus.PRELIMINARY,{"distance_to_host":0.0,"orientation_deg":angle,"room_ownership":room.id,"clearance_rule_available":bool(placement_rules)}))
    return out


def placement_qa(placements: List[EquipmentPlacement]) -> Dict[str,Any]:
    errors=[]; warnings=[]
    for p in placements:
        if p.point is None: errors.append(f"missing_point:{p.equipment_id}")
        if p.room_id is None: errors.append(f"missing_room:{p.equipment_id}")
        if p.host_type=="wall" and not p.host_id: errors.append(f"missing_host:{p.equipment_id}")
        if not p.qa.get("clearance_rule_available",True): warnings.append(f"clearance_rule_missing:{p.equipment_id}")
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"warnings":warnings,"count":len(placements)}
