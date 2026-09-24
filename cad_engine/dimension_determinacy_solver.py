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
    """Build a bipartite element/reference constraint graph."""
    graph=defaultdict(set)
    evidence=defaultdict(list)
    for row in intents or []:
        a=_ref_id(row.get("reference_a"));b=_ref_id(row.get("reference_b"))
        if not a or not b:continue
        graph[a].add(b);graph[b].add(a);evidence[a].append(row);evidence[b].append(row)
    stable=set(str(x) for x in stable_reference_ids or [])
    reachable=set(stable);q=deque(stable)
    while q:
        n=q.popleft()
        for nxt in graph.get(n,()):
            if nxt not in reachable:reachable.add(nxt);q.append(nxt)
    results=[]
    for e in elements or []:
        eid=str(e.get("id") or "")
        kind=e.get("geometry_kind","POINT")
        rows=[r for r in intents or [] if eid in {_ref_id(r.get("reference_a")),_ref_id(r.get("reference_b"))}]
        if kind=="POINT":
            complete=eid in reachable and (_independent_axes(rows) or bool(e.get("intrinsically_hosted")))
            dof_required=0 if e.get("intrinsically_hosted") else 2
            dof_proven=2 if complete else min(1,len(rows))
        else:
            complete=eid in reachable or bool(e.get("intrinsically_hosted"))
            dof_required=int(e.get("required_constraints",1))
            dof_proven=dof_required if complete else min(dof_required,len(rows))
        results.append({"element_id":eid,"priority_class":e.get("priority_class","P1"),"complete":bool(complete),
                        "required_constraints":dof_required,"proven_constraints":dof_proven,
                        "datum_path_exists":eid in reachable or bool(e.get("intrinsically_hosted")),
                        "intent_ids":[r.get("id") for r in rows]})
    critical=[r for r in results if r["priority_class"] in {"P0","P1"} and not r["complete"]]
    return {"status":"PASS" if not critical else "FAIL","elements":results,"critical_missing":critical,
            "stable_reference_ids":sorted(stable),"graph_nodes":len(graph)}


def minimum_constraint_set(candidate_intents,elements,stable_reference_ids):
    """Select a deterministic minimum element-locating set plus required context/CHECKs.

    Candidate dimensions are not individually mandatory. Construction-critical
    elements are mandatory. Point targets receive the smallest independent pair
    of constraints; line-like targets receive the best single locating
    constraint unless explicitly hosted.
    """
    intents=list(candidate_intents or [])
    elements=list(elements or [])
    element_ids={str(e.get("id") or "") for e in elements}
    selected=[];selected_ids=set()

    # Required global/profile context and intentional checks survive by role.
    for row in intents:
        a=_ref_id(row.get("reference_a"));b=_ref_id(row.get("reference_b"))
        touches_element=bool({a,b}&element_ids)
        if row.get("role")=="CHECK" or (row.get("required") and not touches_element):
            if row.get("id") not in selected_ids:
                selected.append(row);selected_ids.add(row.get("id"))

    rank={"P0":0,"P1":1,"P2":2,"P3":3}
    for e in sorted(elements,key=lambda x:(rank.get(x.get("priority_class","P1"),1),str(x.get("id")))):
        eid=str(e.get("id") or "")
        if e.get("intrinsically_hosted"):continue
        rows=[r for r in intents if eid in {_ref_id(r.get("reference_a")),_ref_id(r.get("reference_b"))} and r.get("role")!="CHECK"]
        rows=sorted(rows,key=lambda r:(rank.get(r.get("priority_class","P1"),1),str(r.get("datum_class") or ""),str(r.get("id"))))
        if e.get("geometry_kind","POINT")!="POINT":
            if rows:
                row=rows[0]
                if row.get("id") not in selected_ids:selected.append(row);selected_ids.add(row.get("id"))
            continue
        best=None
        for i,a in enumerate(rows):
            for b in rows[i+1:]:
                if _independent_axes([a,b]):
                    key=(rank.get(a.get("priority_class","P1"),1)+rank.get(b.get("priority_class","P1"),1),
                         str(a.get("id")),str(b.get("id")))
                    if best is None or key<best[0]:best=(key,a,b)
        if best:
            for row in best[1:]:
                if row.get("id") not in selected_ids:selected.append(row);selected_ids.add(row.get("id"))
        elif rows:
            # Keep the best available evidence so QA can explain the missing DOF.
            row=rows[0]
            if row.get("id") not in selected_ids:selected.append(row);selected_ids.add(row.get("id"))

    final=build_determinacy_graph(elements,selected,stable_reference_ids)
    return {"selected":selected,"determinacy":final,"removed_count":len(intents)-len(selected)}
