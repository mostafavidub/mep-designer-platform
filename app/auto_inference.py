import math
import re
from collections import Counter

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
DEFAULT_WATER_VELOCITY_MPS = 1.5


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
    if not re.search(r'ارتفاع|height|floor height|سقف کاذب|false ceiling', text):
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
        if not re.search(r'پکیج|رادیاتور|گرمایش از کف|boiler|radiator|floor heating', text):
            q.append(('heating', 'سیستم گرمایش موردنظر کارفرما چیست؟ اگر انتخابی ندارید بنویسید «پیشنهاد سیستم».'))
        if not re.search(r'اسپلیت|چیلر|فن.?کویل|vrf|split|chiller|fan.?coil', text):
            q.append(('cooling', 'سیستم سرمایش موردنظر کارفرما چیست؟ اگر انتخابی ندارید بنویسید «پیشنهاد سیستم».'))
        if not re.search(r'گاز|gas', text):
            q.append(('gas', 'آیا ساختمان انشعاب گاز دارد و تجهیزات گازسوز در نظر گرفته شده است؟'))
        if not re.search(r'مخزن|پمپ|tank|pump|water meter|کنتور آب', text):
            q.append(('water_source', 'اگر محل ورود آب، مخزن یا پمپ از قبل قطعی است بفرمایید؛ در غیر این صورت بنویسید «پیشنهاد شود».'))
        if not re.search(r'فاضلاب شهری|چاه|sewer|septic', text):
            q.append(('sanitary_outlet', 'مقصد فاضلاب پروژه شبکه شهری است یا چاه/سپتیک؟'))
        if auto.get('detected_parking'):
            q.append(('parking_enclosure', 'پارکینگ شناسایی شد. پارکینگ باز است یا بسته/محصور؟'))

        # Authority-ready mechanical documents cannot be completed from room
        # labels alone. Collect the project-specific engineering inputs that
        # control pipe sizing, slopes, equipment schedules and safe discharge.
        q.append(('fixture_schedule', 'اگر سمبل تجهیزات بهداشتی در معماری قابل تشخیص نیست، تعداد دقیق هر تجهیز را اعلام کنید؛ مثال: روشویی ۳، توالت ۳، دوش ۳، سینک ۱.'))
        q.append(('water_design_basis', 'فشار استاتیک آب ورودی بر حسب bar، جنس لوله، ضریب Hazen-Williams به‌صورت C=… و محدودیت افت فشار را اعلام کنید.'))
        q.append(('sanitary_design_basis', 'جنس لوله فاضلاب، تراز اتصال به شبکه/چاه و شیب مجاز اجرایی را اعلام کنید.'))
        if not re.search(r'بدون گاز|گاز ندارد|no gas', text):
            q.append(('gas_appliances', 'فهرست تجهیزات گازسوز، ظرفیت هر دستگاه بر حسب kW، فشار ورودی بر حسب mbar و محل کنتور/رگلاتور را اعلام کنید.'))
        q.append(('equipment_schedule', 'نوع، ظرفیت و محل قطعی تجهیزات گرمایش و سرمایش را برای هر فضا اعلام کنید؛ ظرفیت‌ها باید با kW یا BTU/h و محل یونیت داخلی/بیرونی مشخص باشند.'))
        q.append(('ventilation_design_basis', 'دبی طراحی سرویس‌ها و پارکینگ را بر حسب m³/h اعلام کنید و مسیر قطعی تخلیه و هوای جبرانی را نیز مشخص کنید؛ ACH بدون حجم فضا برای طراحی نهایی کافی نیست.'))
        if any('بام' in str(x.get('name') or '') or 'roof' in str(x.get('name') or '').lower() for x in (auto.get('levels') or [])):
            q.append(('roof_drainage_basis', 'مساحت مؤثر بام بر حسب m²، تعداد عددی و محل کف‌خواب‌ها و شدت بارندگی طراحی بر حسب mm/h را اعلام کنید.'))

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
    return items
