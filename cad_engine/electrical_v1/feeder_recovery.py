"""Semantic recovery for canonical Electrical service feeders.

The public answer key remains ``riser_feeder_schedule`` for backward workflow
compatibility, but engineering truth is radial MAIN -> floor panel. This module
translates only explicit user/project evidence and never invents feeder values.
"""
from __future__ import annotations

import re


def _number(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    match = re.search(r"[-+]?\d+(?:[.,٫]\d+)?", text)
    return float(match.group(0).replace("٫", ".").replace(",", ".")) if match else None


def _pairs(value):
    result = {}
    for token in re.split(r"[;]+", str(value or "")):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            key, raw = token.split("=", 1)
        else:
            continue
        result[key.strip().lower()] = raw.strip()
    return result


def parse_feeder_schedule(value):
    if isinstance(value, dict):
        rows = []
        for key, raw in value.items():
            if isinstance(raw, dict):
                rows.append((str(raw.get("panel") or key or ""), raw))
    else:
        text = str(value or "").strip()
        if not text:
            return {}
        rows = []
        for index, line in enumerate((x.strip() for x in text.splitlines() if x.strip()), 1):
            explicit = re.search(r"(DB-LVL-\d{3})", line, re.I)
            panel_id = explicit.group(1).upper() if explicit else f"DB-LVL-{index:03d}"
            payload = line.split(":", 1)[1] if explicit and ":" in line else line
            rows.append((panel_id, _pairs(payload.replace(",", ";"))))

    result = {}
    for panel_key, raw in rows:
        panel_id = str(raw.get("panel") or raw.get("تابلو") or panel_key or "").strip().upper()
        if not panel_id.startswith("DB-LVL-"):
            continue
        cable = raw.get("cable") or raw.get("کابل")
        breaker = raw.get("breaker") or raw.get("protection") or raw.get("حفاظت")
        route_length = _number(raw.get("route_length_m") or raw.get("route_length") or raw.get("length_m") or raw.get("طول"))
        tag = raw.get("tag") or raw.get("تگ")
        if cable and breaker and route_length is not None and tag:
            result[panel_id] = {
                "cable": cable, "breaker": breaker,
                "route_length_m": route_length, "tag": tag,
            }
    return result


def install():
    from . import production

    if getattr(production, "_canonical_feeder_recovery_installed", False):
        return
    original = production.build_engine_config

    def build_engine_config(answers, plan_analysis=None):
        cfg = original(answers, plan_analysis)
        explicit = parse_feeder_schedule(dict(answers or {}).get("riser_feeder_schedule"))
        if explicit:
            service_inputs = dict(cfg.get("service_inputs") or {})
            existing = dict(service_inputs.get("feeders") or {})
            # Structured canonical service_inputs remain authoritative when both
            # forms are explicitly present; the flat recovery answer fills gaps.
            service_inputs["feeders"] = {**explicit, **existing}
            cfg["service_inputs"] = service_inputs
        return cfg

    production.build_engine_config = build_engine_config
    production._canonical_feeder_recovery_installed = True
