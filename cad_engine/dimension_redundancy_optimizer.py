"""Semantic redundancy/check optimizer for Dimension Engine v2."""
from __future__ import annotations


def _rid(ref):return str((ref or {}).get("id") or (ref or {}).get("element_id") or "")
def _key(row):
    return (str(row.get("drawing_profile") or ""),str(row.get("purpose") or ""),str(row.get("role") or ""),
            tuple(sorted((_rid(row.get("reference_a")),_rid(row.get("reference_b"))))),
            round(float(row.get("measured_value") or 0.0),8))

def optimize_dimensions(intents):
    seen={};selected=[];removed=[]
    for row in intents or []:
        key=_key(row)
        if key not in seen:
            seen[key]=row;selected.append(row);continue
        existing=seen[key]
        if row.get("role")=="CHECK" or existing.get("role")=="CHECK":
            # A CHECK is semantically distinct from SETOUT even if numerically derivable.
            if row.get("id")!=existing.get("id"):selected.append(row)
            continue
        removed.append({"id":row.get("id"),"reason":"EXACT_SEMANTIC_DUPLICATE","kept":existing.get("id")})
    pair_groups={}
    for r in selected:
        pair=tuple(sorted((_rid(r.get("reference_a")),_rid(r.get("reference_b")))))
        pair_groups.setdefault(pair,[]).append(r)
    alternatives=[]
    for pair,rows in pair_groups.items():
        setouts=[r for r in rows if r.get("role")=="SETOUT"]
        if len(setouts)>1:
            purposes={r.get("purpose") for r in setouts}
            values={round(float(r.get("measured_value") or 0),8) for r in setouts}
            if len(values)>1:
                alternatives.append({"reference_pair":pair,"reason":"CONTRADICTORY_REFERENCE_PAIR","intent_ids":[r.get("id") for r in setouts]})
            elif len(purposes)>1:
                alternatives.append({"reference_pair":pair,"reason":"ALTERNATIVE_PURPOSE_DEFINITION","intent_ids":[r.get("id") for r in setouts]})
    return {"status":"FAIL" if any(x["reason"]=="CONTRADICTORY_REFERENCE_PAIR" for x in alternatives) else "PASS",
            "selected":selected,"removed":removed,"alternatives":alternatives,
            "duplicate_count":len(removed)}
