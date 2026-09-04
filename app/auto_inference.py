import math
import re
from collections import Counter

from .mechanical_rulebook import (
    DEFAULT_GAS_PROPOSAL,
    DEFAULT_WATER_INLET_PRESSURE,
    RULEBOOK_VERSION,
    WATER,
    automatic_answers,
    fixture_schedule_proposal,
    roof_geometry_proposal,
)

ROOM_RULES = {
    'kitchen': ['kitchen', 'آشپزخانه', 'اشپزخانه'],
    'bath': ['bath', 'bathroom', 'حمام'],
    'toilet': ['toilet', 'wc', 'w.c', 'سرویس', 'توالت'],
    'bedroom': ['bedroom', 'bed', 'اتاق خواب', 'خواب'],
    'living': ['living', 'lounge', 'پذیرایی', 'نشیمن', 'هال'],
    'parking': ['parking', 'پارکینگ'],
    'corridor': ['corridor', 'hall', 'راهرو', 'لابی'],
    'shaft': ['shaft', 'duct', 'شفت', 'داکت'],
    'roof': ['roof', 'بام'],
    'stair': ['stair', 'staircase', 'پله', 'راه پله'],
    'elevator': ['elevator', 'lift', 'آسانسور'],
    'office': ['office', 'اداری', 'دفتر'],
    'shop': ['shop', 'commercial', 'تجاری', 'فروشگاه'],
    'pool': ['pool', 'استخر'],
    'sauna': ['sauna', 'سونا'],
    'jacuzzi': ['jacuzzi', 'جکوزی'],
    'boiler_room': ['boiler room', 'mechanical room', 'موتورخانه'],
}

INSUNITS_TO_M = {
    1: 0.0254,  # inch
    2: 0.3048,  # foot
    4: 0.001,   # mm
    5: 0.01,    # cm
    6: 1.0,     # m
}

DEFAULT_OUTPUT_LANGUAGE = 'fa-with-latin-technical-tags'
DEFAULT_VOLTAGE_DROP_PCT = 3.0
DEFAULT_POWER_FACTOR = 0.90
DEFAULT_WATER_VELOCITY_MPS = WATER['target_velocity_mps']


def _project_text(files):
    return ' '.join(str(t) for f in (files or []) for t in (f.get('texts') or []))


def _detected_location(files):
    text = _project_text(files)
    for city in ('مشهد', 'تهران', 'شیراز', 'تبریز', 'اصفهان', 'Mashhad', 'Tehran', 'Shiraz', 'Tabriz', 'Isfahan'):
        if city.lower() in text.lower():
            return city
    return None


def _detected_height(files):
    text = _project_text(files)
    match = re.search(r'(?:ارتفاع|height|floor.?to.?floor)[^\d]{0,20}(\d+(?:[\.,]\d+)?)\s*(m|متر|cm|سانتی.?متر)', text, re.I)
    return f'{match.group(1).replace(",", ".")} {match.group(2)}' if match else None


def _detected_pressure(files):
    text = _project_text(files)
    match = re.search(r'(\d+(?:[\.,]\d+)?)\s*(bar|بار)', text, re.I)
    return f'{match.group(1).replace(",", ".")} bar' if match else None


def _detected_sanitary_outlet(files):
    text = _project_text(files).lower()
    if re.search(r'فاضلاب شهری|municipal sewer|public sewer', text, re.I):
        return 'municipal sewer'
    if re.search(r'چاه|سپتیک|septic', text, re.I):
        return 'septic / well'
    return None


def normalize_text(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip().lower()


def classify_room(text):
    s = normalize_text(text)
    for room, keys in ROOM_RULES.items():
        if any(normalize_text(k) in s for k in keys):
            return room
    return None


def room_counts_from_files(files):
    counts = Counter()
    for f in files or []:
        seen = []
        for text in f.get('texts') or []:
            room = classify_room(text)
            if room:
                key = (room, normalize_text(text))
                if key not in seen:
                    seen.append(key)
                    counts[room] += 1
    return dict(counts)


def detect_occupancy(files, rooms):
    all_text = ' '.join(normalize_text(t) for f in files or [] for t in (f.get('texts') or []))
    if any(x in all_text for x in ['مسکونی', 'residential', 'apartment', 'آپارتمان']):
        return 'residential'
    if any(x in all_text for x in ['اداری', 'office']):
        return 'office'
    if any(x in all_text for x in ['تجاری', 'commercial', 'shop', 'فروشگاه']):
        return 'commercial'
    if rooms.get('bedroom', 0) and rooms.get('kitchen', 0):
        return 'residential'
    if rooms.get('office', 0):
        return 'office'
    if rooms.get('shop', 0):
        return 'commercial'
    return None


def _plausible_area_from_file(f):
    area = f.get('geometry_area_m2')
    try:
        area = float(area)
    except (TypeError, ValueError):
        return None
    # Guard against title blocks / wrong units. We only use plausible building-sized geometry.
    if 15 <= area <= 15000:
        return area
    return None


def estimate_floor_area_m2(files):
    areas = [a for f in files or [] if (a := _plausible_area_from_file(f)) is not None]
    if not areas:
        return None
    return round(sum(areas), 2)


def estimate_route_length_m(files):
    values = []
    for f in files or []:
        w = f.get('geometry_width_m')
        h = f.get('geometry_height_m')
        try:
            w, h = float(w), float(h)
        except (TypeError, ValueError):
            continue
        if 2 <= w <= 500 and 2 <= h <= 500:
            values.append(0.55 * math.hypot(w, h))
    if not values:
        return None
    # Conservative representative route, not a final circuit path.
    return round(max(values), 2)


def estimate_electrical_load_kw(rooms, area_m2=None):
    # Architecture-derived connected-load proxy. It is intentionally conservative and remains preliminary.
    load = 0.0
    load += rooms.get('bedroom', 0) * 0.55
    load += rooms.get('living', 0) * 0.90
    load += rooms.get('kitchen', 0) * 5.50
    load += rooms.get('bath', 0) * 0.35
    load += rooms.get('toilet', 0) * 0.20
    load += rooms.get('corridor', 0) * 0.20
    load += rooms.get('parking', 0) * 0.80
    load += rooms.get('stair', 0) * 0.20
    if area_m2:
        # Baseline common lighting/general-use allowance; room rules dominate dedicated loads.
        load = max(load, area_m2 * 0.025)
    return round(load, 2) if load > 0 else None


def estimate_water_flow_lps(rooms):
    # Simplified architecture-derived probable-demand proxy from inferred plumbing fixtures.
    fixture_units = (
        rooms.get('kitchen', 0) * 2.0
        + rooms.get('bath', 0) * 4.0
        + rooms.get('toilet', 0) * 3.0
    )
    if fixture_units <= 0:
        return None
    return round(max(0.20, 0.16 * math.sqrt(fixture_units)), 3)


def estimate_thermal_loads_kw(rooms, area_m2=None):
    if area_m2:
        # Preliminary generic load-density proxies only; climate/envelope refinement occurs later.
        cooling = area_m2 * 0.12
        heating = area_m2 * 0.09
        return round(cooling, 2), round(heating, 2)
    conditioned_equiv = rooms.get('bedroom', 0) * 1.6 + rooms.get('living', 0) * 3.0 + rooms.get('office', 0) * 2.0
    if conditioned_equiv <= 0:
        return None, None
    return round(conditioned_equiv, 2), round(conditioned_equiv * 0.75, 2)


def infer_architecture_facts(analysis, discipline):
    files = (analysis or {}).get('files') or []
    rooms = room_counts_from_files(files)
    area = estimate_floor_area_m2(files)
    route = estimate_route_length_m(files)
    occupancy = detect_occupancy(files, rooms)
    auto = {
        'source': 'architecture-dxf',
        'room_counts': rooms,
        'occupancy_inferred': occupancy,
        'geometry_area_m2': area,
        'estimated_route_length_m': route,
        'detected_shafts': rooms.get('shaft', 0),
        'detected_parking': rooms.get('parking', 0),
        'detected_roof': rooms.get('roof', 0),
        'detected_elevator': rooms.get('elevator', 0),
        'output_language': DEFAULT_OUTPUT_LANGUAGE,
        'location_inferred': _detected_location(files),
        'floor_height_inferred': _detected_height(files),
        'water_inlet_pressure_inferred': _detected_pressure(files),
        'sanitary_outlet_inferred': _detected_sanitary_outlet(files),
        'gas_absence_inferred': bool(re.search(r'بدون\s*گاز|گاز\s*ندارد|no\s+gas', _project_text(files), re.I)),
        'assumptions': [],
    }
    if discipline == 'electrical':
        auto.update({
            'estimated_electrical_load_kw': estimate_electrical_load_kw(rooms, area),
            'estimated_cable_route_m': route,
            'power_factor': DEFAULT_POWER_FACTOR,
            'max_voltage_drop_pct': DEFAULT_VOLTAGE_DROP_PCT,
        })
        auto['assumptions'].extend([
            'Connected load is estimated from detected architectural room types and generic allowances.',
            'Cable route length is a geometry-derived preliminary representative route, not a final circuit route.',
        ])
    else:
        cool, heat = estimate_thermal_loads_kw(rooms, area)
        auto.update({
            'estimated_water_flow_lps': estimate_water_flow_lps(rooms),
            'target_water_velocity_mps': DEFAULT_WATER_VELOCITY_MPS,
            'estimated_cooling_load_kw': cool,
            'estimated_heating_load_kw': heat,
        })
        auto['assumptions'].extend([
            'Water demand is estimated from architecture-inferred fixture groups and is preliminary.',
            'Thermal loads are architecture-derived proxies and require climate/envelope refinement before construction use.',
        ])
    return auto


def canonical_auto_answers(auto, discipline):
    a = {'architectural_auto': auto, 'language': DEFAULT_OUTPUT_LANGUAGE}
    occupancy = auto.get('occupancy_inferred')
    if occupancy:
        a['occupancy'] = occupancy
    if auto.get('location_inferred'):
        a['location'] = auto['location_inferred']
    if auto.get('floor_height_inferred'):
        a['heights'] = auto['floor_height_inferred']
    if discipline == 'electrical':
        if auto.get('estimated_electrical_load_kw') is not None:
            a['design_load_kw'] = str(auto['estimated_electrical_load_kw'])
        if auto.get('estimated_cable_route_m') is not None:
            a['cable_length_m'] = str(auto['estimated_cable_route_m'])
        a['power_factor'] = str(auto.get('power_factor', DEFAULT_POWER_FACTOR))
        a['max_voltage_drop_pct'] = str(auto.get('max_voltage_drop_pct', DEFAULT_VOLTAGE_DROP_PCT))
    else:
        if auto.get('estimated_water_flow_lps') is not None:
            a['design_water_flow_lps'] = str(auto['estimated_water_flow_lps'])
        a['target_water_velocity_mps'] = str(auto.get('target_water_velocity_mps', DEFAULT_WATER_VELOCITY_MPS))
        if auto.get('estimated_cooling_load_kw') is not None:
            a['cooling_load_kw'] = str(auto['estimated_cooling_load_kw'])
        if auto.get('estimated_heating_load_kw') is not None:
            a['heating_load_kw'] = str(auto['estimated_heating_load_kw'])
        a.update(automatic_answers(auto))
        if auto.get('floor_height_inferred'):
            a['heights'] = auto['floor_height_inferred']
        if auto.get('water_inlet_pressure_inferred'):
            a['water_inlet_pressure'] = auto['water_inlet_pressure_inferred']
        if auto.get('sanitary_outlet_inferred'):
            a['sanitary_outlet'] = auto['sanitary_outlet_inferred']
        if auto.get('gas_absence_inferred'):
            a['gas'] = 'ندارد — inferred from architecture text'
        if auto.get('roof_area_m2') and auto.get('roof_drain_count'):
            a['roof_drainage_geometry'] = (
                f"{auto['roof_area_m2']} m2 roof; {int(auto['roof_drain_count'])} drains at architecture low points"
            )
    return a


def _texts(analysis):
    return ' '.join(normalize_text(t) for f in (analysis or {}).get('files') or [] for t in (f.get('texts') or []))


def dynamic_questions(analysis, discipline, auto):
    text = _texts(analysis)
    q = []

    # Only ask for information that cannot be reliably computed from a 2D architecture plan.
    if not re.search(r'\b(mashhad|tehran|shiraz|tabriz|isfahan|مشهد|تهران|شیراز|تبریز|اصفهان)\b', text):
        q.append(('location', 'شهر و محل پروژه کجاست؟ این مورد برای شرایط اقلیمی و الزامات محلی لازم است.'))
    if not auto.get('occupancy_inferred'):
        q.append(('occupancy', 'کاربری دقیق ساختمان چیست؟ این مورد از پلان با اطمینان کافی تشخیص داده نشد.'))
    if discipline == 'electrical' and not auto.get('floor_height_inferred') and not re.search(r'ارتفاع|height|floor height|سقف کاذب|false ceiling', text):
        q.append(('heights', 'ارتفاع طبقات و وضعیت سقف کاذب را بفرمایید؛ این اطلاعات در پلان دوبعدی پیدا نشد.'))

    if discipline == 'electrical':
        if not re.search(r'3\s*ph|three.?phase|سه.?فاز|1\s*ph|single.?phase|تک.?فاز', text):
            q.append(('supply', 'نوع انشعاب برق پروژه تک‌فاز است یا سه‌فاز؟ اگر ولتاژ نامی خاصی دارد ذکر کنید.'))
        if not re.search(r'generator|ups|ژنراتور|برق اضطراری', text):
            q.append(('emergency', 'آیا پروژه ژنراتور، UPS یا برق اضطراری نیاز دارد؟'))
        if auto.get('detected_elevator'):
            q.append(('elevator', 'آسانسور در پلان تشخیص داده شد. توان/نوع برق آسانسور یا مشخصات سازنده را در صورت موجود بودن بفرمایید.'))
        q.append(('special_loads', 'آیا بار الکتریکی خاصی خارج از آنچه از پلان قابل تشخیص است دارید؟ مثل جکوزی، سونا، پمپ خاص، شارژر خودرو یا تجهیزات صنعتی. اگر ندارید بنویسید «ندارد».'))
    else:
        if not re.search(r'موتورخانه|boiler room|mechanical room|بدون موتورخانه', text, re.I):
            q.append(('has_boiler_room', 'آیا پروژه موتورخانه مرکزی دارد؟'))
        if not re.search(r'استخر|pool|بدون استخر', text, re.I):
            q.append(('has_pool', 'آیا پروژه استخر دارد؟'))
        if not re.search(r'سونا|sauna|بدون سونا', text, re.I):
            q.append(('has_sauna', 'آیا پروژه سونا دارد؟'))
        if not re.search(r'جکوزی|jacuzzi|بدون جکوزی', text, re.I):
            q.append(('has_jacuzzi', 'آیا پروژه جکوزی دارد؟'))
        if not re.search(r'اطفای حریق|اسپرینکلر|sprinkler|fire suppression', text, re.I):
            q.append(('has_fire_suppression', 'آیا طراحی سیستم اطفای حریق در محدوده این پروژه است؟'))
        # Project facts below materially change routing or sizing and cannot be
        # safely replaced by a generic Rule Book value.  Every prompt accepts a
        # short confirmation of a transparent conservative proposal.
        if not auto.get('floor_height_inferred') and not re.search(r'ارتفاع|height|floor height|سقف کاذب|false ceiling', text):
            q.append(('heights', 'ارتفاع طبقه و سقف کاذب مشخص نیست. پیشنهاد: «۳٫۲۰ متر؛ سقف کاذب فضاهای تر ۴۰ سانتی‌متر». پاسخ کوتاه: «تأیید» یا فقط مقدار متفاوت.'))
        # Heating and cooling are owner/design decisions. Symbols or notes in
        # architecture are useful evidence, but must never silently choose the
        # system on the customer's behalf.
        q.append(('heating', 'سیستم گرمایش پروژه را انتخاب کنید.'))
        q.append(('cooling', 'سیستم سرمایش پروژه را انتخاب کنید.'))
        if not auto.get('gas_absence_inferred'):
            q.append(('gas', f'پیشنهاد Rule Book برای پروژه گازدار: پکیج ۲۴ kW، اجاق ۱۰ kW، فشار ۲۱ mbar و کنتور/رگلاتور در ورودی. پاسخ کوتاه: «تأیید»، «بدون گاز» یا اصلاح مورد خاص.'))
        if not auto.get('water_inlet_pressure_inferred') and not re.search(r'\d+(?:[\.,]\d+)?\s*(?:bar|بار)', text, re.I):
            q.append(('water_inlet_pressure', 'فشار واقعی آب در کنتور چند bar است؟ پاسخ کوتاه عددی؛ اگر اندازه‌گیری نشده: «نامشخص» تا مبنای محافظه‌کارانه ۲٫۵ bar همراه مخزن/بوستر اعمال شود.'))
        if not re.search(r'کنتور آب|مخزن|بوستر|پمپ آب|water meter|storage tank|booster', text, re.I):
            q.append(('water_source', 'آرایش ورودی آب چیست؟ پیشنهاد: «کنتور شهری + مخزن + بوسترپمپ». پاسخ کوتاه: «تأیید» یا حذف/اصلاح اجزا.'))
        if not re.search(r'محل انشعاب آب|نقطه ورود آب|water service|water entry|meter location', text, re.I):
            q.append(('water_service_connection', 'محل ورود انشعاب/کنتور آب در کدام ضلع یا نقطه پروژه است؟ پاسخ کوتاه مثل «ضلع جنوبی کنار ورودی»؛ اگر قطعی نیست: «پیشنهاد نزدیک ورودی».'))
        if not re.search(r'فاضلاب شهری|چاه|sewer|septic', text):
            q.append(('sanitary_outlet', 'نوع، محل و تراز خروج فاضلاب چیست؟ پیشنهاد: «شبکه شهری در مرز جنوبی، تراز مبنا ±۰٫۰۰». پاسخ کوتاه: «تأیید»، «چاه/سپتیک» یا فقط محل/تراز متفاوت.'))
        if auto.get('detected_parking'):
            q.append(('parking_enclosure', 'پارکینگ شناسایی شد. پارکینگ باز است یا بسته/محصور؟'))

        if not re.search(r'شفت مکانیکی|رایزر مکانیکی|mechanical shaft|mechanical riser', text, re.I):
            q.append(('mechanical_shaft_route', 'کدام شفت/مسیر عمودی برای تأسیسات مکانیکی مجاز است؟ پاسخ کوتاه مثل «شفت کنار راه‌پله»؛ اگر تصمیم نشده: «پیشنهاد نزدیک هسته فضاهای تر».'))

        if not re.search(r'\b\d+(?:[\.,]\d+)?\s*(?:kw|btu(?:/h|hr)?|ton)\b|کیلووات|تن تبرید', text, re.I):
            q.append(('equipment_schedule', 'ظرفیت یا مدل قطعی تجهیزات گرمایش/سرمایش موجود است؟ پاسخ کوتاه با ظرفیت هر دستگاه؛ اگر نیست: «محاسبه و پیشنهاد بر اساس بار هر فضا».'))

        if not re.search(r'\b(?:ach|m3/h|m³/h)\b|تعویض هوا|دبی تهویه|محل تخلیه|هوای جبرانی', text, re.I):
            q.append(('ventilation_design_basis', 'مسیر تخلیه هوا و هوای جبرانی مشخص است؟ پیشنهاد: «تخلیه بالای بام/نما و هوای جبرانی از بازشوهای نما؛ دبی طبق محاسبه». پاسخ کوتاه: «تأیید» یا فقط مسیر متفاوت.'))

        if not re.search(r'برگشت آب گرم|hot water return|dhwr|آبگرمکن|منبع آب گرم', text, re.I):
            q.append(('hot_water_system', 'تولید آب گرم و نیاز به خط برگشت چگونه است؟ پیشنهاد: «پکیج/منبع مرکزی؛ برگشت برای مسیرهای طولانی». پاسخ کوتاه: «تأیید»، «بدون برگشت» یا مدل دیگر.'))

        # Authority-ready mechanical documents cannot be completed from room
        # labels alone. Collect the project-specific engineering inputs that
        # control pipe sizing, slopes, equipment schedules and safe discharge.
        if not auto.get('fixture_blocks_detected'):
            proposal = fixture_schedule_proposal(auto)
            if any(int((auto.get('room_counts') or {}).get(key) or 0) for key in ('kitchen', 'bath', 'toilet')):
                q.append(('fixture_schedule', f'پیشنهاد خودکار تجهیزات بر اساس فضاهای معماری: {proposal}. پاسخ کوتاه: «تأیید» یا فقط اصلاح تعدادهای متفاوت.'))
            else:
                q.append(('fixture_schedule', 'سمبل تجهیزات بهداشتی با اطمینان تشخیص داده نشد. فقط تعدادها را کوتاه بنویسید؛ مثال: «سینک ۲، روشویی ۳، توالت ۳، دوش ۲».'))
        if auto.get('roof_scope_reliable'):
            if not auto.get('roof_drain_count') or not auto.get('roof_area_m2'):
                proposal = roof_geometry_proposal(auto)
                q.append(('roof_drainage_geometry', f'پیشنهاد خودکار بام: {proposal}. شدت بارندگی از شهر پروژه تعیین می‌شود. پاسخ کوتاه: «تأیید» یا فقط عدد متفاوت مساحت/کف‌خواب.'))

        if not re.search(r'مبحث ۱۴|ضوابط شهرداری|نظام مهندسی|استاندارد محلی|municipal code|local code', text, re.I):
            q.append(('local_mechanical_code', 'آیا شهرداری/نظام مهندسی ضابطه خاصی مثل شدت بارندگی، نوع سیستم یا محدودیت مسیر ابلاغ کرده است؟ پاسخ کوتاه: «ندارد» یا فقط همان الزام.'))

    return q


def auto_summary(auto, discipline):
    rooms = auto.get('room_counts') or {}
    labels = sum(rooms.values())
    items = [f'{labels} برچسب فضای معماری تشخیص داده شد']
    if auto.get('geometry_area_m2'):
        items.append(f"مساحت هندسی قابل‌اعتماد تقریبی {auto['geometry_area_m2']} m²")
    if discipline == 'electrical' and auto.get('estimated_electrical_load_kw') is not None:
        items.append(f"بار پایه معماری به‌صورت خودکار ≈ {auto['estimated_electrical_load_kw']} kW")
    if discipline == 'mechanical' and auto.get('estimated_water_flow_lps') is not None:
        items.append(f"دبی اولیه آب از Fixtureهای تشخیص‌داده‌شده ≈ {auto['estimated_water_flow_lps']} L/s")
    if discipline == 'mechanical':
        items.append(f'جنس لوله، ضرایب هیدرولیکی، شیب‌ها، فشار مبنای محافظه‌کارانه، دبی پایه تهویه و انتخاب اولیه تجهیزات توسط Rule Book v{RULEBOOK_VERSION} تعیین می‌شود')
        if auto.get('fixture_blocks_detected'):
            items.append(f"{auto['fixture_blocks_detected']} سمبل واقعی تجهیزات مکانیکی/بهداشتی از DXF تشخیص داده شد")
    return items
