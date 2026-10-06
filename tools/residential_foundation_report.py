#!/usr/bin/env python3
"""Export a read-only research packet; no candidate generation or production writes."""
import argparse
import html
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cad_engine.residential_foundation import foundation_audit, load_catalog
from cad_engine.residential_symbols import create_symbol, symbol_svg

def export(destination):
    destination.mkdir(parents=True,exist_ok=True)
    audit=foundation_audit()
    (destination/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    esc=html.escape
    parts=['<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><title>پایهٔ طراحی پلان مسکونی — PLANHA</title><style>body{font:17px/1.9 Tahoma,sans-serif;max-width:1180px;margin:30px auto;padding:20px;color:#183247;background:#f7fafb}h1,h2{color:#14675e}article{background:white;padding:18px;margin:16px 0;border:1px solid #ccd9de;border-radius:10px}code,pre{direction:ltr;unicode-bidi:isolate;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #ccd9de;vertical-align:top}a{color:#126e85}svg{height:160px;max-width:220px}small{color:#536875}details{margin:10px 0}summary{cursor:pointer}input,textarea,select{font:inherit;max-width:100%;box-sizing:border-box}</style><body><h1>پایهٔ طراحی پلان مسکونی</h1><article><b>وضعیت: پایهٔ پژوهشی ناقص؛ نیازمند تکمیل منابع و بازبینی معماری</b><p>این بسته مجوز طراحی خودکار یا ساخت نیست. قواعد عددی تا تأیید نسخه، اصلاحیه و دامنهٔ کاربرد فعال نمی‌شوند. هیچ پلان اینترنتی به‌عنوان نمونهٔ طلایی تأیید نشده است.</p><p>خروجی هدف: فقط پلان طبقات مسکونی یکسان. طراحی نما، مقطع، سازه و محاسبات تأسیسات خارج از این نسخه است.</p></article>']
    nav=[('research-completion','نتیجهٔ تکمیل پژوهش'),('golden-review-template','فرم Golden انسانی'),('sources','منابع و وضعیت نسخه‌ها'),('rulebook','قواعد معماری'),('exam-coverage','پوشش منابع آزمون'),('plan-study','مطالعهٔ پلان‌ها'),('heuristics','الگوهای طراحی'),('symbols','نمادهای پارامتریک'),('owner-questionnaire','پرسش‌نامهٔ مالک'),('qa-matrix','ماتریس کنترل کیفیت'),('generation-contract','قرارداد تولید')]
    parts.append('<nav>'+ ' | '.join(f'<a href="#{n}">{t}</a>' for n,t in nav)+'</nav>')
    for name,title in nav:
        data=load_catalog(name)
        envelope={'build_identity':audit['build_identity'],'catalog':data}
        (destination/(name+'.json')).write_text(json.dumps(envelope,ensure_ascii=False,indent=2)+'\n')
        parts.append(f'<h2 id="{name}">{title}</h2><p><a href="{name}.json">دادهٔ کامل و قابل پیگیری</a></p>')
        if name=='research-completion':
            parts.append('<article><p><b>وضعیت:</b> پژوهش هنوز برای فعال‌کردن قواعد یا تولید خودکار کافی نیست.</p><p>هر ۳۲ استخراج مبحث چهارم از نظر محل و انتقال محتوا ممیزی شده‌اند، اما احراز ویرایش جاری، همهٔ استثناها، تعارض منابع و بازبینی مستقل کامل نشده است؛ بنابراین تعداد قواعد فعال صفر باقی می‌ماند.</p><p>۲۴ شکاف به نتیجه‌های مشخص مانند نیاز به ورودی پروژه، منبع مفقود، مدل ضوابط محلی، ترجیح مالک یا بازبینی متخصص طبقه‌بندی شده‌اند.</p><details><summary>قرارداد کامل پژوهش، ارگونومی و Golden</summary><pre>'+esc(json.dumps(data,ensure_ascii=False,indent=2))+'</pre></details></article>')
        elif name=='golden-review-template':
            parts.append('<article><p>این فرم خالی است و Golden محسوب نمی‌شود. معمار مستقل باید آن را فقط از منابع پروژه تکمیل و پیش از مشاهدهٔ خروجی Planha مهر زمانی و قفل کند.</p><ol>'+''.join('<li>'+esc(x)+'</li>' for x in data['instructions_fa'])+'</ol><details><summary>ساختار کامل فرم</summary><pre>'+esc(json.dumps(data,ensure_ascii=False,indent=2))+'</pre></details></article>')
        elif name=='sources':
            parts.append('<table><tr><th>منبع</th><th>سال</th><th>وضعیت بررسی</th></tr>')
            for s in data['sources']:parts.append(f'<tr><td>{esc(s["title"])}</td><td dir="ltr">{s.get("edition_year") or "—"}</td><td><code>{esc(s["status"])}</code><br>{esc(s.get("notes", ""))}</td></tr>')
            parts.append('</table>')
        elif name=='rulebook':
            for r in data['rules']:parts.append(f'<article><code>{esc(r["rule_id"])}</code><h3>{esc(r["title_fa"])}</h3><p>{esc(r["requirement_fa"])}</p><small>فعال برای صدور تأیید: خیر — نسخه و دامنهٔ کاربرد باید تأیید شود.</small><details><summary>شرایط و سند مرجع</summary><pre>{esc(json.dumps(r,ensure_ascii=False,indent=2))}</pre></details></article>')
        elif name=='owner-questionnaire':
            parts.append('<p>این صفحه برای بررسی مدل پرسش‌نامه است. پاسخ پروژه‌ای دریافت یا ذخیره نمی‌کند. ابتدا سؤال‌های ضروری، سپس شاخه‌های مرتبط و در پایان ترجیحات اختیاری پرسیده می‌شوند. اطلاعاتی مانند شهر، اقلیم و ضوابط از دادهٔ معتبر پروژه استخراج می‌شوند.</p>')
            for step in data['v1_progression']:
                parts.append('<h3>'+step['title_fa']+'</h3>')
                for q in data['questions']:
                    if q['question_id'] not in step['question_ids']:continue
                    labels=q.get('option_labels_fa',{})
                    parts.append(f'<article><code>{esc(q["question_id"])}</code><p>{esc(q["text_fa"])}</p><small>{esc(q["why_fa"])}</small>')
                    if labels:parts.append('<p>گزینه‌ها: '+' / '.join(esc(v) for v in labels.values())+'</p>')
                    if q['condition']:parts.append('<details><summary>چه زمانی پرسیده می‌شود؟</summary><pre>'+esc(json.dumps(q['condition'],ensure_ascii=False))+'</pre></details>')
                    parts.append('</article>')
        elif name=='plan-study':
            s=data['summary'];parts.append(f'<p>{s["actual_plan_count"]} پلان از {s["distinct_projects"]} پروژه به‌صورت تصویری بررسی شده است. {s["context_only_count"]} مورد صرفاً زمینهٔ مقایسه است. ناشر اصلی همهٔ نمونه‌ها ArchDaily است؛ این مجموعه نمونه‌گیری تصادفی یا مطالعهٔ آماری بازار نیست.</p>')
            parts.append('<p>هیچ تصویر یا نقشهٔ دارای حق نشر در این بسته بازنشر نشده است. یادداشت‌های فنی تفصیلی فعلاً انگلیسی‌اند. مقدار خالی یعنی آن ویژگی تأیید نشده است.</p>')
            for r in data['records']:parts.append(f'<details><summary><code>{r["study_id"]}</code> — {esc(r["source_title"])}</summary><p><a href="{esc(r["source_url"],quote=True)}">صفحهٔ مرجع</a></p><p dir="ltr">{esc(r["reviewed_view"])}: {esc(r["observation"])}</p><p dir="ltr">{esc(r["notable_weakness_or_risk"])}</p></details>')
        elif name=='heuristics':
            for h in data['heuristics']:parts.append(f'<article><code>{h["heuristic_id"]}</code><p>{esc(h["description_fa"])}</p><small>دیده‌شده در {h["project_frequency"]} پروژه از {h["project_denominator"]}؛ ضابطهٔ قانونی نیست. تکرار مشاهده، اثبات کیفیت نیست.</small></article>')
        elif name=='symbols':
            parts.append('<p>شکل‌ها کاملاً پارامتریک و ساخته‌شده در این پروژه‌اند. اندازه‌های نمونه صرفاً برای نمایش‌اند؛ فاصلهٔ استفاده، ابعاد محصول و محل اتصال تأسیسات باید با مرجع معتبر تعیین شوند.</p>')
            for row in data['symbols']:
                symbol=create_symbol(row['symbol_id'],width_m=1,depth_m=1.5,origin_m=[0,0],rotation_deg=0,dimension_basis='VISUALIZATION_ONLY',steps=8)
                svg=symbol_svg(symbol);(destination/(row['symbol_id']+'.svg')).write_text(svg)
                parts.append(f'<article><code>{row["symbol_id"]}</code><br>{svg}<p>نمونهٔ ترسیمی؛ ابعاد و قابلیت استفاده تأیید نشده است.</p></article>')
        elif name=='qa-matrix':parts.append('<p>ماتریس، سناریوهای لازم برای موتور آینده را مشخص می‌کند. وجود سناریو به معنای اجرای آن نیست. آزمون‌های اجراشدهٔ پایه در گزارش تحویل جدا آمده‌اند.</p>')
        elif name=='generation-contract':parts.append('<p>تولید پیشنهادی مرحله‌ای است: اعتبار منابع ← برنامهٔ مالک ← محدودهٔ ساخت ← هستهٔ مشترک ← تقسیم واحدها ← فضاها و بازشوها ← مبلمان و رزرو تأسیسات ← کنترل الزامات ← رتبه‌بندی کیفیت. موتور جست‌وجوی چیدمان هنوز پیاده‌سازی نشده است. پایان زمان جست‌وجو، اثبات ناممکن بودن طرح نیست.</p>')
    parts.append('<h2>هویت خودکار این خروجی</h2><pre>'+esc(json.dumps(audit,ensure_ascii=False,indent=2))+'</pre></body></html>')
    (destination/'index.html').write_text('\n'.join(parts))
    return audit

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    a=export(args.output);print(json.dumps({'status':a['status'],'plan_count':a['actual_plan_count'],'output':str(args.output)},ensure_ascii=False))
