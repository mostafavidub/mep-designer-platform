"""Graph-theoretic construction determinacy and over-constraint analysis."""
from __future__ import annotations
from collections import defaultdict, deque

STABLE_DATUM_KINDS={"GRID_AXIS","PROPERTY","PROPERTY_BOUNDARY","GRID","SITE_DATUM","PLAN_EDGE"}

def _rid(ref):
    return str((ref or {}).get("id") or (ref or {}).get("element_id") or "")

def analyze_determinacy(critical_reference_ids, intents, references, *, datum_ids=None):
    refs={str(r.get("id")):r for r in references or [] if r.get("id")}
    datums=set(str(x) for x in (datum_ids or []))
    if not datums:
        datums={rid for rid,r in refs.items() if str(r.get("kind") or "").upper() in STABLE_DATUM_KINDS or str(r.get("subfeature") or "").upper()=="GRID_AXIS"}
    graph=defaultdict(set); definitions=defaultdict(list)
    for row in intents or []:
        if row.get("purpose")=="CHECK":
            continue
        a=_rid(row.get("reference_a")); b=_rid(row.get("reference_b"))
        if not a or not b:
            continue
        graph[a].add(b); graph[b].add(a)
        definitions[tuple(sorted((a,b)))].append(row.get("id"))
    reachable=set(datums); q=deque(datums)
    while q:
        cur=q.popleft()
        for nxt in graph[cur]:
            if nxt not in reachable:
                reachable.add(nxt); q.append(nxt)
    critical={str(x) for x in critical_reference_ids or []}
    missing=sorted(critical-reachable)
    duplicates=[{"pair":pair,"intent_ids":ids} for pair,ids in definitions.items() if len(ids)>1]
    return {
        "status":"PASS" if not missing else "UNDER_DIMENSIONED",
        "datum_ids":sorted(datums),"reachable_ids":sorted(reachable),
        "missing_reference_ids":missing,"duplicate_independent_definitions":duplicates,
    }

def analyze_overdimensioning(intents):
    pairs=defaultdict(list)
    for row in intents or []:
        if row.get("purpose")=="CHECK":
            continue
        a=_rid(row.get("reference_a")); b=_rid(row.get("reference_b"))
        if a and b:
            pairs[tuple(sorted((a,b)))].append(row)
    errors=[]
    for pair,rows in pairs.items():
        independent=[r for r in rows if not r.get("check_group_id")]
        if len(independent)>1:
            errors.append({"pair":pair,"reason":"MULTIPLE_INDEPENDENT_DEFINITIONS",
                           "intent_ids":[r.get("id") for r in independent]})
    return {"status":"PASS" if not errors else "OVER_DIMENSIONED","errors":errors}
