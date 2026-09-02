"""Website presentation contract for the exact mechanical Drawing Manifest."""
from html import escape


TYPE_LABELS = {
    'floor_plan': 'پلان سیستم',
    'roof_plan': 'پلان بام / آب باران',
    'riser_diagram': 'دیاگرام رایزر',
    'schematic': 'شماتیک',
    'equipment_plan': 'پلان تجهیزات',
    'detail_sheet': 'شیت جزئیات',
    'ventilation_plan': 'پلان تهویه',
}


def review_question_html_v12(drawing_set):
    drawing_set = drawing_set or {}
    manifest = drawing_set.get('drawing_manifest') or {}
    sheets = manifest.get('sheets') or drawing_set.get('deliverable_sheets') or []
    total = int(manifest.get('total_sheets') or drawing_set.get('deliverable_sheet_count') or 0)
    manifest_id = str(manifest.get('manifest_id') or '')

    rows = []
    for sheet in sheets:
        code = escape(str(sheet.get('code') or ''))
        label = escape(str(sheet.get('label') or sheet.get('family') or 'Mechanical'))
        drawing_type = TYPE_LABELS.get(str(sheet.get('drawing_type') or ''), str(sheet.get('drawing_type') or 'شیت مکانیکی'))
        drawing_type = escape(drawing_type)
        levels = [str(x) for x in (sheet.get('levels') or [])]
        if sheet.get('typical') and len(levels) > 1:
            scope = 'Typical: ' + '، '.join(levels)
        else:
            scope = '، '.join(levels) or escape(str(sheet.get('pattern') or 'System special'))
        scope = escape(scope)
        special = ' <span style="color:#B54708;font-weight:700">ویژه</span>' if sheet.get('special') else ''
        rows.append(
            '<tr>'
            f'<td style="padding:7px 8px;border-bottom:1px solid #EAECF0;white-space:nowrap"><b>{code}</b></td>'
            f'<td style="padding:7px 8px;border-bottom:1px solid #EAECF0">{label}{special}</td>'
            f'<td style="padding:7px 8px;border-bottom:1px solid #EAECF0">{drawing_type}</td>'
            f'<td style="padding:7px 8px;border-bottom:1px solid #EAECF0">{scope}</td>'
            '</tr>'
        )

    body = ''.join(rows) or '<tr><td colspan="4">Manifest آماده نیست.</td></tr>'
    manifest_short = escape(manifest_id[:12]) if manifest_id else '—'
    return (
        '<div style="text-align:right;font-size:15px;line-height:1.8">'
        '<div style="font-size:21px;font-weight:800;margin-bottom:5px">پیشنهاد دقیق نقشه‌های مکانیکی پروژه</div>'
        '<p style="color:#667085;margin:0 0 10px">این جدول همان Drawing Manifest است که پس از تأیید فریز می‌شود و Code Designer فقط مجاز به تولید همین شیت‌هاست.</p>'
        f'<div style="font-size:19px;font-weight:800;margin:8px 0 4px">تعداد شیت‌های تحویلی مکانیک: {total} شیت</div>'
        f'<div style="font-size:12px;color:#98A2B3;margin-bottom:12px">Manifest ID: {manifest_short}</div>'
        '<div style="max-height:340px;overflow:auto;border:1px solid #EAECF0;border-radius:10px">'
        '<table style="width:100%;border-collapse:collapse;font-size:13px">'
        '<thead><tr style="background:#F9FAFB"><th style="padding:7px">کد</th><th style="padding:7px">خانواده</th><th style="padding:7px">نوع نقشه</th><th style="padding:7px">طبقه / محدوده</th></tr></thead>'
        f'<tbody>{body}</tbody></table></div>'
        '<p style="font-size:13px;color:#667085;margin:10px 0">تعداد طبقات معماری با تعداد شیت‌های تأسیساتی یکی نیست. طبقات Typical فقط در همان سیستم و فقط وقتی تأیید شده باشند ادغام می‌شوند.</p>'
        '<p style="font-size:13px;color:#344054;background:#F2F4F7;padding:9px 11px;border-radius:8px;margin:10px 0">در پلان‌های سرمایش، نمایش خوانای سمبل‌های IDU/ODU، تگ و ظرفیت، Leader، جهت پرتاب هوا، مسیر مبرد و درین و پریویوی مستقل هر شیت بخشی از قرارداد تحویل است؛ نبود هرکدام Release را متوقف می‌کند.</p>'
        '<p style="font-size:13px;color:#344054;background:#F2F4F7;padding:9px 11px;border-radius:8px;margin:10px 0">جهت شمال فقط از نماد همان پلان معماری خوانده و حفظ می‌شود؛ فلش شمال دوم تولید نمی‌شود. کادر چاپ داخلی، نوار عنوان/مقیاس قدیمی و اجزای خارج از خود پلان نیز از تمام شیت‌های تحویلی حذف می‌شوند.</p>'
        '<p style="font-size:13px;color:#344054;background:#F2F4F7;padding:9px 11px;border-radius:8px;margin:10px 0">اگر خطای عملیاتی قابل‌اصلاح رخ دهد، سامانه حداکثر سه تلاش کنترل‌شده با نمایش مرحله و ثبت سابقه انجام می‌دهد؛ اطلاعات مهندسی ناقص یا خطای ناشناخته هرگز حدس زده نمی‌شود.</p>'
        '<style>#answerForm textarea,#answerForm>button{display:none!important}</style>'
        '<button type="button" class="btn primary wide" onclick="document.getElementById(\'answer\').value=\'تأیید\';document.getElementById(\'answerForm\').requestSubmit()">تأیید همین Manifest و شروع طراحی</button>'
        '</div>'
    )


def install(review_fix_module):
    review_fix_module.review_question_html = review_question_html_v12
    review_fix_module.MANIFEST_PRESENTATION_VERSION = '12.1'
