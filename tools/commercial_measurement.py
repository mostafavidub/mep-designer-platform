#!/usr/bin/env python3
"""Private offline commercial projection and Golden request from existing models."""
import argparse
import html
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.commercial_measurement import measure
from app.commercial_golden import golden_request, benchmark
from app.commercial_shadow import persist_shadow


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path,help='Private project/source/model path manifest; never commit.')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text()); reports=[]; requests=[]
    for project in manifest['projects']:
        bundles=[{k:json.loads(Path(source[k]).read_text()) for k in ('canonical','legacy')} for source in project['sources']]
        report=measure(project['project_id'],bundles,current_sources=[s['source_sha256'] for s in project['sources']])
        persist_shadow(args.output,report); reports.append(report)
        frames=[{'source_sha256':row['source_sha256'],'frame_id':row['frame_id'],
                 'source_evidence':row['source_evidence']} for row in report['levels']]
        requests.append(golden_request(project['project_id'],[s['source_sha256'] for s in project['sources']],frames,report['build_identity']))
    args.output.mkdir(exist_ok=True,parents=True)
    (args.output/'golden-requests.json').write_text(json.dumps(requests,indent=2,ensure_ascii=False)+'\n')
    (args.output/'benchmark.json').write_text(json.dumps(benchmark(reports),indent=2,ensure_ascii=False)+'\n')
    sections=[]
    for request in requests:
        cards=''.join('<li><bdi dir="ltr">'+html.escape(f['frame_id'])+'</bdi> — '+html.escape(str(f['source_evidence'].get('raw_text') or 'عنوان نامشخص'))+'</li>' for f in request['observed_frame_inventory_not_truth'])
        sections.append('<section><h2><bdi dir="ltr">'+html.escape(request['project_id'])+'</bdi></h2><p>این فهرست، خروجی تشخیص است و فهرست تأییدشدهٔ طبقات نیست.</p><ul>'+cards+'</ul></section>')
    page='''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><title>بررسی مرجع مساحت تجاری</title>
<style>body{font-family:Tahoma,sans-serif;line-height:1.9;max-width:1000px;margin:2rem auto;padding:1rem;color:#192738;background:#f4f6f8}section{background:white;padding:1.4rem;margin:1rem 0;border-radius:12px}bdi{unicode-bidi:isolate}a{color:#0755a3}</style>
<h1>بررسی مستقل مساحت ناخالص پروژه‌ها</h1><p>وضعیت: اطلاعات مرجع انسانی لازم است. هنوز هیچ قیمت مشتری از این داده‌ها صادر نمی‌شود.</p>
<p>لطفاً فقط برای یک پروژهٔ کامل در مرحلهٔ اول، تعداد ساختمان‌ها و تمام طبقات واقعی، از جمله پلان‌های جاافتاده، را مشخص کنید. برای هر طبقه، شناسهٔ پلان، نوع/کاربری، تعداد تکرارِ اثبات‌شده و مساحت ناخالصِ مستقلاً اندازه‌گیری‌شده را همراه روش اندازه‌گیری و نام بررسی‌کننده ثبت کنید.</p>
<p>زیرزمین، پارکینگ، نیم‌طبقه، بالکن و تراس قابل محاسبه‌اند. فقط بام و حیاط/سایت از صورت‌حساب کنار گذاشته می‌شوند؛ همچنان ممکن است نیاز به طراحی مهندسی داشته باشند. فضاهای داخلی مانند دیوار و راه‌پله نباید از مساحت ناخالص کم شوند.</p>
<p>مساحت‌های مرجع برای سنجش کیفیت‌اند؛ پاسخ انسانی نمی‌تواند هندسهٔ جدیدی برای موتور بسازد. هیچ عددی از خروجی الگوریتم به عنوان پاسخ درست پر نشده است. شناسه‌ها با نقشهٔ اصلی تطبیق داده شوند؛ در نبود مدرک مقدار را خالی بگذارید.</p>
<p><a href="golden-requests.json">دریافت فرم داده‌های مرجع</a></p>'''+''.join(sections)+'</html>'
    (args.output/'golden-review.html').write_text(page)
    print(json.dumps({'projects':len(reports),'status':'HUMAN_GOLDEN_REQUIRED','provider_calls':0}))


if __name__=='__main__': main()
