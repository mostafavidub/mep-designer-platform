"""Machine-readable Rule Book for fixture and mechanical-equipment recognition.

Detection rules are evidence-based. Weak hints create candidates; strong or
corroborated spatial evidence is required before a downstream design engine may
count an installed fixture/equipment item.
"""

RULEBOOK_VERSION = "2.4-fixture-equipment-approved-symbols"
DETECTION_VERSION = "fixture-equipment-v2"

DETECTED_THRESHOLD = 0.78
CANDIDATE_THRESHOLD = 0.60

FIXTURE_ALIASES = {
    "toilet": (
        "toilet", "wc", "water closet", "closet", "toalet", "klozet", "farangi",
        "توالت", "فرنگی", "توالت فرنگی", "توالت ایرانی", "کاسه توالت",
    ),
    "basin": (
        "wash basin", "washbasin", "basin", "lavabo", "lavatory", "lav", "lave",
        "روشویی", "روشويی", "دستشویی", "دستشويی",
    ),
    "sink": ("kitchen sink", "sink", "سینک", "سينک"),
    "faucet": ("faucet", "tap", "water tap", "شیر آب", "شير آب"),
    "shower": ("shower", "دوش"),
    "bathtub": ("bathtub", "bath tub", "tub", "وان"),
    "floor_drain": (
        "floor drain", "floordrain", "floor-drain", "kafshoor", "kaf shoor", "fd",
        "کفشور", "کف شور", "کفخواب", "کف خواب",
    ),
    "urinal": ("urinal", "یورینال", "يورينال", "آبریزگاه"),
    "dishwasher": ("dishwasher", "ظرفشویی", "ماشین ظرفشویی"),
    "washing_machine": ("washing machine", "washer", "لباسشویی", "ماشین لباسشویی"),
}

EQUIPMENT_ALIASES = {
    "boiler": ("boiler", "پکیج", "پکيج", "دیگ", "ديگ"),
    "water_heater": ("water heater", "waterheater", "آبگرمکن"),
    "radiator": ("radiator", "rad", "رادیاتور", "رادياتور"),
    "fan_coil": ("fan coil", "fancoil", "fcu", "فن کویل", "فن‌کویل", "فن کويل"),
    "split_indoor": ("indoor unit", "split indoor", "indoor split", "اسپلیت داخلی", "یونیت داخلی"),
    "split_outdoor": ("outdoor unit", "odu", "condenser unit", "یونیت خارجی", "کندانسینگ یونیت"),
    "exhaust_fan": ("exhaust fan", "exh fan", "ef-", "اگزاست فن", "هواکش"),
    "ahu": ("ahu", "air handling unit", "هواساز"),
    "chiller": ("chiller", "چیلر", "چيلر"),
    "pump": ("pump", "پمپ"),
    "tank": ("water tank", "storage tank", "tank", "مخزن"),
    "gas_cooker": ("gas cooker", "cooker", "stove", "k_gaz", "k gaz", "اجاق", "گاز رومیزی", "گاز روميزی"),
    "kitchen_hood": ("kitchen hood", "hood", "هود"),
}

FIXTURE_LAYER_HINTS = {
    "toilet": ("wc", "toilet", "closet", "toalet"),
    "basin": ("basin", "lav", "lave", "washbasin"),
    "sink": ("sink", "kitchen"),
    "faucet": ("faucet", "tap"),
    "shower": ("shower",),
    "bathtub": ("bathtub", "tub"),
    "floor_drain": ("floor-drain", "floor_drain", "floordrain", "drain", "fd"),
    "urinal": ("urinal",),
}

EQUIPMENT_LAYER_HINTS = {
    "boiler": ("boiler",),
    "water_heater": ("water-heater", "water_heater"),
    "radiator": ("radiator", "rad"),
    "fan_coil": ("fcu", "fan-coil", "fancoil"),
    "split_indoor": ("indoor-unit", "indoor_unit", "split"),
    "split_outdoor": ("outdoor-unit", "outdoor_unit", "odu", "condenser"),
    "exhaust_fan": ("exhaust", "exh", "ef", "fan"),
    "ahu": ("ahu",),
    "chiller": ("chiller",),
    "pump": ("pump",),
    "tank": ("tank",),
    "gas_cooker": ("gas", "gaz", "cooker", "stove"),
    "kitchen_hood": ("hood",),
}

GENERIC_FIXTURE_LAYER_TOKENS = (
    "fixture", "plumbing", "sanitary", "toilet", "bath", "kitchen", "لوازم", "بهداشتی",
)
GENERIC_EQUIPMENT_LAYER_TOKENS = (
    "equipment", "equip", "mechanical", "hvac", "تجهیزات", "مکانیک",
)

SIGNAL_SCORES = {
    "block_name": 0.92,
    "explicit_text": 0.82,
    "typed_layer": 0.80,
    "nearby_text": 0.76,
    "generic_layer_plus_geometry": 0.66,
}
CORROBORATION_BONUS = 0.06
TEXT_ONLY_MAX_CONFIDENCE = 0.70
WET_ROOM_TYPES = ("kitchen", "bath", "toilet")
