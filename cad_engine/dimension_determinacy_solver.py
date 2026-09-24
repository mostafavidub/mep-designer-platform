"""Graph-based construction determinacy for Dimension Engine v2."""
from __future__ import annotations
import math
from collections import defaultdict,deque


def _ref_id(ref):
    return str((ref or {}).get("id") or (ref or {}).get("element_id") or "")

def _independent_axes(constraints,tol_deg=5.0):
    angles=[]
    for c in constraints:
        if c.get("implicit_host"): 
            angles.append(float(c.get("axis_deg",0.0)))
            continue
        a=c.get("axis_deg")
        if a is not None:angles.append(float(a)%180.0)
    if len(angles)<2:return False
    for i,a in enumerate(angles):
        for b in angles[i+1:]:
            d=abs(a-b)%180.0;d=min(d,180.0-d)
            if d>tol_deg and abs(d-180.0)>tol_deg:return True
    return False


def build_determinacy_graph(elements,intents,stable_reference_ids):
    """Prove each required locating DOF from stable datum paths."""
    graph=defaultdict(set)
    stable=set(str(x) for x in stable_reference_ids or [])
    for row in intents or []:
        a=_ref_id(row.get("reference_a"));b=_ref_id(row.get("reference_b"))
        if not a or not b:continue
        graph[a].add(b);graph[b].add(a)
    reachable=set(stable);q=deque(stable)
    while q:
        n=q.popleft()
        for nxt in graph.get(n,()):
            if nxt not in reachable:reachable.add(nxt);q.append(nxt)

    results=[]
    for e in elements or []:
        eid=str(e.get("id") or "")
        required=list(e.get("required_dofs") or ([] if e.get("intrinsically_hosted") else (["LOC_0","LOC_1"] if e.get("geometry_kind","POINT")=="POINT" else ["OFFSET","START","END"])))
        rows=[r for r in intents or [] if eid==str(((r.get("reference_a") or {}).get("element_id") or (r.get("reference_a") or {}).get("id") or ""))]
        proven={str(r.get("constraint_dof")) for r in rows if r.get("constraint_dof") and _ref_id(r.get("reference_b")) in reachable}
        if e.get("intrinsically_hosted"):
            proven.update(required)
        missing=[d for d in required if d not in proven]
        complete=not missing
        results.append({"element_id":eid,"priority_class":e.get("priority_class","P1"),"complete":complete,
                        "required_dofs":required,"proven_dofs":sorted(proven),"missing_dofs":missing,
                        "required_constraints":len(required),"proven_constraints":len([d for d in required if d in proven]),
                        "datum_path_exists":bool(proven) or bool(e.get("intrinsically_hosted")),
                        "intent_ids":[r.get("id") for r in rows]})
    critical=[r for r in results if r["priority_class"] in {"P0","P1"} and not r["complete"]]
    return {"status":"PASS" if not critical else "FAIL","elements":results,"critical_missing":critical,
            "stable_reference_ids":sorted(stable),"graph_nodes":len(graph)}



def minimum_constraint_set(candidate_intents,elements,stable_reference_ids):
    """Select one best constraint per unresolved DOF plus intentional CHECKs."""
    intents=list(candidate_intents or []);elements=list(elements or [])
    selected=[];selected_ids=set()
    element_ids={str(e.get("id") or "") for e in elements}
    rank={"P0":0,"P1":1,"P2":2,"P3":3}

    # Global/context requirements and explicit CHECKs survive.
    for row in intents:
        a=str(((row.get("reference_a") or {}).get("element_id") or (row.get("reference_a") or {}).get("id") or ""))
        touches=a in element_ids
        if row.get("role")=="CHECK" or (row.get("required") and not touches):
            if row.get("id") not in selected_ids:selected.append(row);selected_ids.add(row.get("id"))

    for e in sorted(elements,key=lambda x:(rank.get(x.get("priority_class","P1"),1),str(x.get("id")))):
        if e.get("intrinsically_hosted"):continue
        eid=str(e.get("id") or "")
        required=list(e.get("required_dofs") or (["LOC_0","LOC_1"] if e.get("geometry_kind","POINT")=="POINT" else ["OFFSET","START","END"]))
        rows=[r for r in intents if str(((r.get("reference_a") or {}).get("element_id") or ""))==eid and r.get("role")!="CHECK"]
        for dof in required:
            options=[r for r in rows if r.get("constraint_dof")==dof]
            if not options:continue
            options=sorted(options,key=lambda r:(rank.get(r.get("priority_class","P1"),1),
                int((r.get("reference_b") or {}).get("priority",50)),
                -float((r.get("reference_b") or {}).get("confidence",1.0)),
                float(r.get("measured_value") or 0.0),str(r.get("id"))))
            row=options[0]
            if row.get("id") not in selected_ids:selected.append(row);selected_ids.add(row.get("id"))

    final=build_determinacy_graph(elements,selected,stable_reference_ids)
    return {"selected":selected,"determinacy":final,"removed_count":len(intents)-len(selected)}
