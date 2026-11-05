"""Consumer-backed metadata for the active Mechanical questionnaire."""

SECTION_ORDER = {
    "general": 10,
    "water_supply": 20,
    "sanitary_vent": 30,
    "heating_cooling": 40,
    "gas": 50,
    "ventilation": 60,
    "rainwater": 70,
}

QUESTION_CATALOG = {
    "location": ("general", "اطلاعات عمومی", ["all"], "mechanical_design_core.build_design_overrides"),
    "city": ("general", "اطلاعات عمومی", ["all"], "mechanical_design_core.build_design_overrides"),
    "occupancy": ("general", "اطلاعات عمومی", ["all"], "mechanical_design_core.build_authority_model"),
    "mechanical_shaft_route": ("general", "اطلاعات عمومی", ["water_supply", "sanitary_vent", "heating_cooling", "gas", "ventilation", "rainwater"], "mechanical_basis_contract.shaft_approval"),
    "water_inlet_pressure": ("water_supply", "آب سرد و گرم", ["water_supply"], "mechanical_design_core.build_design_overrides"),
    "water_source": ("water_supply", "آب سرد و گرم", ["water_supply"], "mechanical_workflow.build_scope"),
    "hot_water_system": ("water_supply", "آب سرد و گرم", ["water_supply"], "mechanical_workflow.build_scope"),
    "fixture_schedule": ("sanitary_vent", "فاضلاب و هواکش", ["water_supply", "sanitary_vent"], "fixture_gate_v1.fixture_evidence_resolved"),
    "heating": ("heating_cooling", "سرمایش و گرمایش", ["heating"], "mechanical_workflow.build_scope"),
    "heating_system": ("heating_cooling", "سرمایش و گرمایش", ["heating"], "mechanical_design_core.build_design_overrides"),
    "cooling": ("heating_cooling", "سرمایش و گرمایش", ["cooling"], "mechanical_workflow.build_scope"),
    "cooling_system": ("heating_cooling", "سرمایش و گرمایش", ["cooling"], "mechanical_design_core.build_design_overrides"),
    "gas": ("gas", "گاز", ["gas"], "mechanical_workflow.build_scope"),
    "gas_pressure": ("gas", "گاز", ["gas"], "mechanical_design_core.build_design_overrides"),
    "gas_relative_density": ("gas", "گاز", ["gas"], "engineering_overlay_materializer.build_engineering_proposal"),
    "parking_enclosure": ("ventilation", "تهویه", ["ventilation"], "mechanical_workflow.build_scope"),
    "max_duct_velocity_m_s": ("ventilation", "تهویه", ["ventilation"], "engineering_overlay_materializer.build_engineering_proposal"),
    "candidate_round_duct_diameters_mm": ("ventilation", "تهویه", ["ventilation"], "engineering_overlay_materializer.build_engineering_proposal"),
    "roof": ("rainwater", "آب باران", ["rainwater"], "mechanical_workflow.build_scope"),
    "rainfall_intensity": ("rainwater", "آب باران", ["rainwater"], "mechanical_design_core.build_design_overrides"),
}

ACTIVE_QUESTION_KEYS = frozenset(QUESTION_CATALOG)
CONDITIONAL_QUESTION_KEYS = frozenset({"gas_pressure", "gas_relative_density", "max_duct_velocity_m_s", "candidate_round_duct_diameters_mm"})
UNSUPPORTED_AMENITY_KEYS = frozenset({"has_boiler_room", "has_pool", "has_sauna", "has_jacuzzi"})


def question_metadata(key):
    spec = QUESTION_CATALOG.get(str(key or ""))
    if not spec:
        return {}
    section_id, section_title, systems, consumer = spec
    return {
        "section_id": section_id,
        "section_title": section_title,
        "section_order": SECTION_ORDER[section_id],
        "systems": list(systems),
        "consumer": consumer,
    }


def decorate_question(question):
    result = dict(question or {})
    result.update(question_metadata(result.get("key") or result.get("id")))
    return result


def question_sort_key(key):
    metadata = question_metadata(key)
    return (metadata.get("section_order", 999),)
