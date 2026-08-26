"""Machine-readable Rule Book for fixture and mechanical-equipment recognition.

Detection rules are intentionally evidence-based.  A weak hint may create a
candidate, but only corroborated evidence is allowed to become a detected item
that downstream design engines can count.
"""

RULEBOOK_VERSION = "2.3-fixture-equipment-detection"
DETECTION_VERSION = "fixture-equipment-v2"

DETECTED_THRESHOLD = 0.78
CANDIDATE_THRESHOLD = 0.60

FIXTURE_ALIASES = {
    "toilet": (
        "toilet", "wc", "water closet", "closet", "toalet", "klozet",
        "توالت", "فرنگی", "توالت فرنگی", "توالت ایرانی", "کاسه توالت",
    ),
    "basin": (
        "wash basin", "washbasin", "basin", "lavabo", "lavatory", "lav",
        "روشویی", "روشويی", "دستشویی", "دستشويی",
    ),
    "sink": ("kitchen sink", "sink", "سینک", "سينک"),
    "shower": ("shower", "دوش"),
    "bathtub": ("bathtub", "bath tub", "tub", "وان"),
    "floor_drain": (
        "floor drain", "floordrain", "floor-drain", "kafshoor", "kaf shoor",
        "کفشور", "کف شور", "کفخواب", "کف خواب",
    ),
    "urinal": ("urinal", "یورینال", "يورينال", "آبریزگاه"),
    "dishwasher": ("dishwasher", "ظرفشویی", "ماشین ظرفشویی"),
    "washing_machine": ("washing machine", "washer", "لباسشویی", "ماشین لباسشویی"),
}

EQUIPMENT_ALIASES = {
    "boiler": ("boiler", "پکیج", "پکيج", "دیگ", "ديگ"),
    "water_heater": ("water heater", "waterheater", "آبگرمکن"),
    "fan_coil": ("fan coil", "fancoil", "fcu", "فن کویل", "فن‌کویل", "فن کويل"),
    "split_indoor": ("indoor unit", "split indoor", "indoor split", "اسپلیت داخلی", "یونیت داخلی"),
    "split_outdoor": ("outdoor unit", "odu", "condenser unit", "یونیت خارجی", "کندانسینگ یونیت"),
    "exhaust_fan": ("exhaust fan", "ef-", "اگزاست فن", "هواکش"),
    "ahu": ("ahu", "air handling unit", "هواساز"),
    "chiller": ("chiller", "چیلر", "چيلر"),
    "pump": ("pump", "پمپ"),
    "tank": ("water tank", "storage tank", "tank", "مخزن"),
    "gas_cooker": ("gas cooker", "cooker", "stove", "اجاق", "گاز رومیزی", "گاز روميزی"),
    "kitchen_hood": ("kitchen hood", "hood", "هود"),
}

# Layer tokens are weaker than an explicit symbol/block name, but they are
# useful in consultant drawings whose blocks are named numerically or exploded.
FIXTURE_LAYER_HINTS = {
    "toilet": ("wc", "toilet", "closet", "toalet"),
    "basin": ("basin", "lav", "washbasin"),
    "sink": ("sink", "kitchen"),
    "shower": ("shower",),
    "bathtub": ("bathtub", "tub"),
    "floor_drain": ("floor-drain", "floor_drain", "floordrain", "drain", "fd"),
    "urinal": ("urinal",),
}

EQUIPMENT_LAYER_HINTS = {
    "boiler": ("boiler",),
    "water_heater": ("water-heater", "water_heater"),
    "fan_coil": ("fcu", "fan-coil", "fancoil"),
    "split_indoor": ("indoor-unit", "indoor_unit", "split"),
    "split_outdoor": ("outdoor-unit", "outdoor_unit", "odu", "condenser"),
    "exhaust_fan": ("exhaust", "ef", "fan"),
    "ahu": ("ahu",),
    "chiller": ("chiller",),
    "pump": ("pump",),
    "tank": ("tank",),
}

GENERIC_FIXTURE_LAYER_TOKENS = (
    "fixture", "plumbing", "sanitary", "toilet", "bath", "kitchen", "لوازم", "بهداشتی",
)
GENERIC_EQUIPMENT_LAYER_TOKENS = (
    "equipment", "equip", "mechanical", "hvac", "تجهیزات", "مکانیک",
)

# Signals and their base confidence. Multiple independent signals are combined
# by taking the strongest score and adding a small corroboration bonus.
SIGNAL_SCORES = {
    "block_name": 0.92,
    "explicit_text": 0.82,
    "typed_layer": 0.80,
    "nearby_text": 0.76,
    "generic_layer_plus_geometry": 0.66,
}
CORROBORATION_BONUS = 0.06

# Text-only annotations can be legends/notes. They are retained as candidates
# unless another spatial signal corroborates them.
TEXT_ONLY_MAX_CONFIDENCE = 0.70

# QA rule for later design gates: a wet architectural level with zero detected
# plumbing fixtures is an unresolved evidence condition, not proof that no
# plumbing fixture exists.
WET_ROOM_TYPES = ("kitchen", "bath", "toilet")
