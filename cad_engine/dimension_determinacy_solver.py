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
    """Greedy deterministic minimum set with mandatory CHECK intents retained.

    Candidate ordering is stable and favors required SETOUT, higher-priority
    targets and stable-reference connections. This is intentionally explainable,
    not an opaque numerical optimizer.
    """
    checks=[r for r in candidate_intents or [] if r.get("role")=="CHECK"]
    setouts=[r for r in candidate_intents or [] if r.get("role")!="CHECK"]
    rank={"P0":0,"P1":1,"P2":2,"P3":3}
    setouts=sorted(setouts,key=lambda r:(rank.get(r.get("priority_class","P1"),1),0 if r.get("required",True) else 1,str(r.get("id"))))
    selected=[]
    last_missing=None
    for row in setouts:
        trial=selected+[row]
        state=build_determinacy_graph(elements,trial,stable_reference_ids)
        missing=len(state["critical_missing"])
        if last_missing is None or missing<last_missing or row.get("required"):
            selected.append(row);last_missing=missing
        if missing==0:
            # Continue only required P0/P1 set-outs; optional redundancy stops.
            continue
    selected.extend(checks)
    final=build_determinacy_graph(elements,selected,stable_reference_ids)
    return {"selected":selected,"determinacy":final,"removed_count":len(candidate_intents or [])-len(selected)}
