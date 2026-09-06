from __future__ import annotations

import math
from typing import Any, Dict, Optional

from .models import EngineeringStatus


def _inside(point, poly):
    if not poly: return False
    x,y=point; hit=False; j=len(poly)-1
    for i,(xi,yi) in enumerate(poly):
        xj,yj=poly[j]
        if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/((yj-yi) or 1e-12)+xi: hit=not hit
        j=i
    return hit


def _dist_point_segment(p,a,b):
    ax,ay=a; bx,by=b; px,py=p; dx,dy=bx-ax,by-ay
    if dx*dx+dy*dy<1e-12:return math.dist(p,a)
    t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy))); q=(ax+t*dx,ay+t*dy);return math.dist(p,q)


def finalize_placements(placements, requirements, project, architecture, rules: Optional[Dict[str,Any]]=None):
    rules=rules or {}; errors=[]; warnings=[]; reqs={r.id:r for r in requirements}; rooms={r.id:r for r in project.rooms}
    unit_scale={"mm":.001,"cm":.01,"m":1.0}.get(architecture.units.value)
    opening_clearance_m=rules.get("opening_clearance_m"); wall_tolerance_m=rules.get("wall_host_tolerance_m"); ceiling_confirmed=rules.get("ceiling_layout_basis_confirmed") is True
    if opening_clearance_m is None: warnings.append("opening_clearance_rule_missing")
    if wall_tolerance_m is None: warnings.append("wall_host_tolerance_missing")
    for p in placements:
        req=reqs.get(p.requirement_id); room=rooms.get(p.room_id)
        if not req or not room or not p.point:
            errors.append(f"placement_context_missing:{p.equipment_id}"); continue
        if req.quantity.status!=EngineeringStatus.FINAL:
            warnings.append(f"quantity_not_final:{p.equipment_id}"); continue
        if p.host_type=="ceiling":
            if room.polygon and _inside(p.point,room.polygon) and ceiling_confirmed:
                p.status=EngineeringStatus.FINAL; p.qa["inside_room_polygon"]=True
            else:
                errors.append(f"ceiling_host_or_polygon_fail:{p.equipment_id}")
        elif p.host_type=="wall":
            if wall_tolerance_m is None or unit_scale is None:
                warnings.append(f"wall_tolerance_basis_missing:{p.equipment_id}"); continue
            distance=float(p.qa.get("distance_to_host",0.0))*unit_scale
            if distance>float(wall_tolerance_m): errors.append(f"distance_to_host:{p.equipment_id}:{distance}"); continue
            conflict=False
            if opening_clearance_m is not None:
                for e in architecture.entities:
                    if e.frame_id!=p.frame_id or e.kind not in {"door","window"}: continue
                    q=e.geometry.get("point")
                    if q and math.dist(p.point,tuple(q))*unit_scale<float(opening_clearance_m):
                        # A switch is intentionally door-related, so its governing offset must be supplied separately.
                        if req.equipment_type!="LIGHT_SWITCH": conflict=True
                if req.equipment_type=="LIGHT_SWITCH" and not rules.get("switch_door_relation_confirmed"):
                    warnings.append(f"switch_door_side_not_confirmed:{p.equipment_id}"); continue
            if conflict: errors.append(f"door_window_conflict:{p.equipment_id}")
            else: p.status=EngineeringStatus.FINAL
    preliminary=[p.equipment_id for p in placements if p.status!=EngineeringStatus.FINAL]
    status="FAIL" if errors else ("PRELIMINARY" if warnings or preliminary else "PASS")
    return {"status":status,"errors":errors,"warnings":warnings+[f"placement_not_final:{x}" for x in preliminary],"final":sum(p.status==EngineeringStatus.FINAL for p in placements),"total":len(placements)}
