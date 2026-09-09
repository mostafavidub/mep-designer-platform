"""Semantic sheet QA for project-driven mechanical drawing sets.

Rejects sheets that are non-empty only because of architecture/frame content,
checks required family layers, verifies family purity, and detects duplicate
mechanical content between comparable sheets after normalizing coordinates to
each sheet's local origin.
"""
from __future__ import annotations
import hashlib
from collections import Counter

IGNORED_LAYERS = {
    "ENGITOOLS-M-SHEET-FRAME", "ENGITOOLS-M-SHEET-TITLE",
    "ENGITOOLS-M-DOC", "ENGITOOLS-M-ANNOTATION",
}

REQUIRED_LAYERS = {
    "GENERAL_DETAIL": {"ENGITOOLS-M-DETAIL"},
    "ROOF": {"ENGITOOLS-M-RAINWATER", "ENGITOOLS-M-VENT-TERM"},
    "SANITARY_VENT": {"ENGITOOLS-M-SANITARY", "ENGITOOLS-M-VENT"},
    "WATER": {"ENGITOOLS-M-COLD_WATER", "ENGITOOLS-M-HOT_WATER"},
    "HEATING": {"ENGITOOLS-M-HEAT-FLOW", "ENGITOOLS-M-HEAT-RETURN", "ENGITOOLS-M-EQUIPMENT"},
    "GAS": {"ENGITOOLS-M-GAS"},
    "PLUMBING_RISER": {"ENGITOOLS-M-RISER-DETAIL"},
    "WATER_SERVICE_CALC": {"ENGITOOLS-M-DETAIL"},
    "GENERAL_NOTES": {"ENGITOOLS-M-DETAIL"},
    "SPLIT_AC": {"ENGITOOLS-M-HVAC-REFRIG", "ENGITOOLS-M-HVAC-COND", "ENGITOOLS-M-EQUIPMENT"},
    "EXHAUST": {"ENGITOOLS-M-EXHAUST"},
    "EQUIPMENT_SCHEDULE": {"ENGITOOLS-M-DETAIL"},
}


def _normalized_token(entity, bounds, resolution=0.05):
    layer = str(entity.get("layer") or "")
    ext = entity.get("extents") or [0, 0, 0, 0]
    vals = [round((ext[0]-bounds[0])/resolution), round((ext[1]-bounds[1])/resolution),
            round((ext[2]-bounds[0])/resolution), round((ext[3]-bounds[1])/resolution)]
    return f"{entity.get('type')}|{layer}|{vals}|{str(entity.get('text') or '')[:80]}"


def evaluate_sheet(sheet, mechanical_entities, special_required=None, min_purity=0.80):
    family = sheet.get("family")
    counts = Counter(str(e.get("layer") or "") for e in mechanical_entities)
    expected = set((special_required or {}).get(sheet.get("sheet"), REQUIRED_LAYERS.get(family, {"ENGITOOLS-M-DETAIL"})))
    if family == "COVER":
        content_count = counts.get("ENGITOOLS-M-DOC", 0)
        return {"status":"PASS" if content_count >= 2 else "FAIL", "content_count":content_count,
                "missing_required_layers":[], "family_purity":1.0 if content_count else 0.0,
                "signature":None, "layer_counts":dict(counts)}
    system = [e for e in mechanical_entities if str(e.get("layer") or "") not in IGNORED_LAYERS]
    missing = [x for x in sorted(expected) if counts.get(x, 0) == 0]
    allowed = set(expected)
    if family in {"SANITARY_VENT", "WATER", "HEATING"}:
        allowed.add("ENGITOOLS-M-RISER")
    purity = (sum(1 for e in system if str(e.get("layer") or "") in allowed) / len(system)) if system else 0.0
    tokens = {_normalized_token(e, sheet["model_bounds"]) for e in system}
    signature = hashlib.sha256("\n".join(sorted(tokens)).encode()).hexdigest() if tokens else None
    status = "PASS" if system and not missing and purity >= min_purity else "FAIL"
    return {"status":status, "content_count":len(system), "missing_required_layers":missing,
            "family_purity":round(purity,3), "signature":signature, "layer_counts":dict(counts)}


def detect_semantic_duplicates(sheet_results):
    pairs=[]
    for i,a in enumerate(sheet_results):
        for b in sheet_results[i+1:]:
            if a.get("family") != b.get("family"): continue
            if a.get("signature") and a.get("signature") == b.get("signature"):
                pairs.append((a.get("sheet"), b.get("sheet"), a.get("family")))
    return pairs
