"""Pure DXF unit-sanity inference shared by analysis and drawing engines."""
from __future__ import annotations

import statistics

INSUNITS_TO_M = {4: 0.001, 5: 0.01, 6: 1.0}


def dimension_measurements(doc):
    values=[]
    for entity in doc.modelspace().query("DIMENSION"):
        try:value=abs(float(entity.get_measurement()))
        except Exception:continue
        if 0.001<=value<=100000:
            values.append(value)
    return values


def infer_drawing_unit_scale(doc):
    """Resolve drawing-unit-to-metre scale without trusting DXF header blindly."""
    insunits=int(doc.header.get("$INSUNITS",0) or 0)
    header_scale=INSUNITS_TO_M.get(insunits)
    values=dimension_measurements(doc)
    median_dim=statistics.median(values) if values else None
    scale=header_scale
    source="header" if header_scale else "unknown"
    confidence="medium" if header_scale else "low"

    # Existing Planha unit-sanity contract. These ranges are plausibility
    # classifiers for source units, never building-design defaults.
    if insunits==4 and median_dim is not None and 0.20<=median_dim<=50.0:
        scale=1.0
        source="dimension-measurement-override-mm-header-to-m"
        confidence="high"
    elif insunits==6 and median_dim is not None and 200.0<=median_dim<=50000.0:
        scale=0.001
        source="dimension-measurement-override-m-header-to-mm"
        confidence="high"

    return {
        "header_insunits":insunits,
        "header_scale_to_m":header_scale,
        "effective_scale_to_m":scale,
        "dimension_count":len(values),
        "median_dimension_drawing_units":round(median_dim,6) if median_dim is not None else None,
        "source":source,
        "confidence":confidence,
    }
