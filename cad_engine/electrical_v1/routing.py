from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .architecture import assert_no_cross_frame_connection
from .models import ArchitecturalModel, ElectricalProjectModel, EngineeringStatus, EvidenceValue, EquipmentPlacement


def _final(ev: EvidenceValue) -> bool:
    return ev.status == EngineeringStatus.FINAL and ev.value is not None


def _orthogonal_path(a: Tuple[float,float], b: Tuple[float,float], offset: float=0.0):
    if abs(a[0]-b[0])<1e-9 or abs(a[1]-b[1])<1e-9:
        return [a,b]
    xmid=b[0]+offset
    return [a,(xmid,a[1]),(xmid,b[1]),b]


def _length(points):
    return sum(math.dist(a,b) for a,b in zip(points,points[1:]))


def _bbox_contains(bounds, p):
    return bounds[0] <= p[0] <= bounds[2] and bounds[1] <= p[1] <= bounds[3]


def route_circuits(topology: Dict[str,Any], placements: List[EquipmentPlacement],
                   architecture: ArchitecturalModel, panel_locations: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    """Route each circuit only inside its owning print frame.

    Vertical relationships are not drawn here; they are represented by the riser
    engine. Missing panel location evidence produces an unrouted circuit rather
    than an invented route.
    """
    panel_locations=panel_locations or {}; placement_by_eq={p.equipment_id:p for p in placements}
    load_by_id={l.id:l for l in topology["loads"]}; routes=[]; errors=[]; warnings=[]
    unit_scale={"mm":.001,"cm":.01,"m":1.0}.get(architecture.units.value) if _final(architecture.units) else None
    frame_map={f.id:f for f in architecture.frames}
    for circuit in topology["circuits"]:
        panel=next((p for p in topology["panels"] if p.id==circuit.panel_id),None)
        loc=panel_locations.get(circuit.panel_id) or panel_locations.get(panel.level_id if panel else "")
        if not isinstance(loc,dict) or not isinstance(loc.get("point"),(list,tuple)) or len(loc["point"])<2:
            warnings.append(f"panel_location_missing:{circuit.id}"); continue
        panel_point=(float(loc["point"][0]),float(loc["point"][1])); panel_frame=loc.get("frame_id")
        route_parts=[]
        for load_id in circuit.load_ids:
            load=load_by_id.get(load_id); placement=placement_by_eq.get(load.equipment_id) if load else None
            if not placement or not placement.point:
                errors.append(f"load_placement_missing:{load_id}"); continue
            try:
                assert_no_cross_frame_connection(placement.frame_id,panel_frame)
            except ValueError as exc:
                errors.append(str(exc)); continue
            frame_id=placement.frame_id or panel_frame
            frame=frame_map.get(frame_id) if frame_id else None
            path=_orthogonal_path(tuple(placement.point),panel_point)
            if frame and not all(_bbox_contains(frame.bounds,p) for p in path):
                errors.append(f"route_outside_owning_frame:{circuit.id}:{load_id}"); continue
            route_parts.append({"load_id":load_id,"points":path,"frame_id":frame_id})
        if route_parts:
            raw_length=sum(_length(x["points"]) for x in route_parts)
            if unit_scale:
                circuit.route_length_m=EvidenceValue.final(raw_length*unit_scale,"engineering_calculation",1.0)
            else:
                circuit.route_length_m=EvidenceValue.input_required("drawing units required for route length")
            routes.append({"circuit_id":circuit.id,"panel_id":circuit.panel_id,"parts":route_parts,"frame_id":route_parts[0]["frame_id"],"length_drawing_units":raw_length})
    routed={r["circuit_id"] for r in routes}; all_ids={c.id for c in topology["circuits"]}
    if all_ids-routed: warnings.append(f"unrouted_circuits:{sorted(all_ids-routed)}")
    return {"status":"FAIL" if errors else ("PRELIMINARY" if warnings else "PASS"),"errors":errors,"warnings":warnings,"routes":routes}


def routing_qa(routing: Dict[str,Any]) -> Dict[str,Any]:
    errors=list(routing.get("errors") or []); warnings=list(routing.get("warnings") or [])
    for route in routing.get("routes") or []:
        for part in route["parts"]:
            points=part["points"]
            for a,b in zip(points,points[1:]):
                if abs(a[0]-b[0])>1e-8 and abs(a[1]-b[1])>1e-8:
                    errors.append(f"non_orthogonal_route:{route['circuit_id']}")
    return {"status":"FAIL" if errors else ("PRELIMINARY" if warnings else "PASS"),"errors":errors,"warnings":warnings,"route_count":len(routing.get("routes") or [])}
