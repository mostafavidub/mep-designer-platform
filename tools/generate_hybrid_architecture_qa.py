#!/usr/bin/env python3
"""Generate the governed Hybrid architecture QA bundle from one model run."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cad_engine.architectural_space_engine import reconstruct_architecture


NAMES = [
    "01-raw-authoritative-render", "02-cad-fact-layer", "03-vision-space-hypotheses",
    "04-vision-boundary-hypotheses", "05-vision-shell-hypotheses", "06-evidence-graph-overlay",
    "07-cad-confirmed-boundaries", "08-multi-evidence-inferred-boundaries",
    "09-conflicting-boundaries", "10-unresolved-boundaries", "11-hybrid-envelope",
    "12-hybrid-physical-spaces", "13-functional-zones", "14-human-question-overlays",
    "15-final-ground-architecture",
]


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("dxf")
    parser.add_argument("output")
    parser.add_argument("--raw-render")
    args=parser.parse_args()
    output=Path(args.output); output.mkdir(parents=True,exist_ok=True)
    # QA generation must never spend provider budget. It consumes the current
    # cache/model state and truthfully marks unavailable Hybrid evidence.
    os.environ["ARCH_VISION_PROVIDER"]="disabled"
    model=reconstruct_architecture(args.dxf)
    ground=next((frame for frame in model["frames"] if frame.get("level_candidate")=="GROUND"),None)
    frame_id=ground and ground["frame_id"]
    common={"source_sha256":model["source"]["source_sha256"],"frame_id":frame_id,
            "status":"BLOCKED_NO_SUCCESSFUL_HYBRID_VISION_EVIDENCE"}
    if args.raw_render and Path(args.raw_render).exists():
        shutil.copyfile(args.raw_render,output/(NAMES[0]+Path(args.raw_render).suffix))
    else:
        _write(output/(NAMES[0]+".json"),common)
    cad={**common,"status":"AVAILABLE","segments":[row for row in model["architectural_segments"]
                                                      if row.get("frame_id") in {None,frame_id}],
         "canonical_walls":[row for row in model["canonical_walls"] if row.get("frame_id")==frame_id]}
    _write(output/(NAMES[1]+".json"),cad)
    for name in NAMES[2:]:
        _write(output/(name+".json"),common)
    summary={"schema":"hybrid-architecture-qa-package/1.0",**common,
             "artifact_names":NAMES,"dxf_parse_count":model["diagnostics"]["dxf_parse_count"],
             "deterministic_status":model["completeness"]["status"],
             "reason":"The single authorized Global provider attempt returned VISION_PROVIDER_UNAVAILABLE; "
                      "no Vision hypothesis or Hybrid result is represented as successful."}
    _write(output/"manifest.json",summary)
    print(json.dumps(summary,ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
