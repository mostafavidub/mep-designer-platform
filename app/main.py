import os, shutil, zipfile, threading, uuid
from pathlib import Path
from datetime import datetime
from collections import Counter

import requests, ezdxf
from .dxf_input import normalize_input_copy, read_input_dxf
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, String, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATA_DIR = Path(os.getenv('DATA_DIR', '/data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_URL = os.getenv('DATABASE_URL', f"sqlite:///{DATA_DIR/'mep.db'}")
RULEBOOK_PATH = os.getenv('RULEBOOK_PATH', str(DATA_DIR/'rulebook/MEP_Design_Rulebook.docx'))
CAD_DESIGNER_URL = os.getenv('CAD_DESIGNER_URL', '').rstrip('/')
SESSION_SECRET = os.getenv('SESSION_SECRET', 'dev-secret-change-me')
INDEXNOW_KEY = os.getenv('INDEXNOW_KEY', '').strip()
connect_args = {'check_same_thread': False} if DB_URL.startswith('sqlite') else {}
engine = create_engine(DB_URL, connect_args=connect_args, pool_pre_ping=True)
Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), default='anonymous')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default='awaiting_upload')
    questions: Mapped[list] = mapped_column(JSON, default=list)
    current_question: Mapped[int] = mapped_column(Integer, default=0)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Revision(Base):
    __tablename__ = 'revisions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    revision_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default='queued')
    feedback: Mapped[str] = mapped_column(Text, default='')
    pdf_path: Mapped[str] = mapped_column(Text, default='')
    error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class RuleCandidate(Base):
    __tablename__ = 'rule_candidates'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer)
    feedback: Mapped[str] = mapped_column(Text)
    candidate_rule: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

COMMON = [
    ('location','پروژه در کدام کشور و شهر قرار دارد؟'),('occupancy','کاربری دقیق ساختمان چیست؟'),('codes','مبنای طراحی کدام مقررات و استانداردهاست؟'),('floors','تعداد طبقات، زیرزمین/پارکینگ و بام را دقیق بفرمایید.'),('units','تعداد کل واحدها و تعداد واحد در هر طبقه چقدر است؟'),('typical','کدام طبقات تیپ هستند و کدام پلان متفاوت دارند؟'),('heights','ارتفاع طبقات و وضعیت سقف کاذب را بفرمایید.'),('shafts','شفت‌ها و رایزرهای موجود قطعی هستند یا اجازه پیشنهاد داریم؟'),('roof','روی بام چه فضاها یا تجهیزاتی دارید؟'),('language','زبان خروجی را مشخص کنید؛ پیشنهاد: توضیحات فارسی و Tagهای فنی لاتین.')]
ELECTRICAL = [('supply','برق واحدها تک‌فاز است یا سه‌فاز؟'),('main_panel','محل کنتورها و تابلوهای اصلی کجاست؟'),('emergency','ژنراتور، UPS یا برق اضطراری دارید؟'),('elevator','آسانسور دارید؟ تعداد و مشخصات برق آن را بفرمایید.'),('loads','بارهای خاص برق مثل کولر، پکیج، پمپ، لباسشویی و ظرفشویی را بفرمایید.'),('lighting','نوع روشنایی و کنترل روشنایی مدنظر چیست؟'),('power','پریزها و مصارف قدرت خاص چه نیازهایی دارند؟'),('elv','سیستم‌های جریان ضعیف موردنیاز را مشخص کنید.'),('fire_alarm','سیستم اعلام حریق چه Scope و زون‌بندی‌ای دارد؟'),('earthing','الزامات ارت و هم‌بندی پروژه را بفرمایید.')]
MECHANICAL = [('heating','سیستم گرمایش چیست؟'),('cooling','سیستم سرمایش چیست؟'),('gas','ساختمان گاز دارد؟ محل ورود گاز و تجهیزات گازسوز را بفرمایید.'),('water','محل ورود آب، مخزن و پمپ مشخص است؟'),('sanitary','خروج فاضلاب/چاه/شبکه شهری مشخص است؟'),('ventilation','سرویس‌ها، آشپزخانه و پارکینگ به نما/شفت تهویه دسترسی دارند؟'),('plumbing','نوع لوله‌کشی آب سرد و گرم و محدودیت‌های اجرایی چیست؟'),('drainage','الزامات فاضلاب، ونت و شیب‌بندی را بفرمایید.'),('hvac','نوع تجهیزات HVAC و محل تقریبی آن‌ها مشخص است؟'),('parking','پارکینگ بسته است یا باز و آیا تهویه مکانیکی لازم دارد؟')]
DISCIPLINES = {'electrical': {'title':'همراه برق','subtitle':'طراحی تخصصی نقشه‌های برق ساختمان','icon':'⚡','questions':COMMON+ELECTRICAL,'accent':'electrical'},'mechanical': {'title':'همراه مکانیک','subtitle':'طراحی تخصصی نقشه‌های مکانیکی ساختمان','icon':'◉','questions':COMMON+MECHANICAL,'accent':'mechanical'}}
OUTPUT_SCOPES = {'electrical': {'label':'Electrical only','systems':['lighting','power','dedicated_loads','fire_alarm','elv','earthing_bonding','panels','single_line_diagram','electrical_risers','electrical_legend_notes']},'mechanical': {'label':'Mechanical only','systems':['cold_water','hot_water','sanitary','vent','gas','heating_supply','heating_return','cooling','condensate','exhaust_ventilation','mechanical_risers','mechanical_details_legend_notes']}}

QUESTION_OPTIONS = {
    'occupancy': ['مسکونی', 'اداری', 'تجاری', 'مختلط'],
    'codes': ['مقررات ملی ساختمان ایران', 'مقررات ملی ایران به‌همراه ضوابط آتش‌نشانی محلی', 'IEC / استانداردهای بین‌المللی', 'طبق ضوابط اعلامی کارفرما یا مشاور'],
    'floors': ['همکف و یک طبقه', '۲ تا ۵ طبقه', '۶ تا ۱۰ طبقه', 'بیش از ۱۰ طبقه'],
    'units': ['یک واحد', '۲ تا ۵ واحد', '۶ تا ۱۰ واحد', 'بیش از ۱۰ واحد'],
    'typical': ['همه طبقات تیپ هستند', 'طبقات مسکونی تیپ و همکف/پارکینگ متفاوت است', 'چند تیپ پلان تکرارشونده داریم', 'هیچ طبقه‌ای تیپ نیست'],
    'heights': ['ارتفاع و سقف کاذب مطابق پلان معماری است', 'سقف کاذب در همه طبقات اجرا می‌شود', 'سقف کاذب فقط در فضاهای مرطوب و راهروهاست', 'سقف کاذب نداریم'],
    'shafts': ['شفت‌ها و رایزرها قطعی هستند', 'محل شفت‌ها قطعی است ولی ابعاد قابل اصلاح است', 'اجازه پیشنهاد محل و ابعاد شفت را دارید', 'شفت مشخص نشده و باید پیشنهاد شود'],
    'roof': ['بام فاقد فضای تأسیساتی ویژه است', 'موتورخانه یا تجهیزات مکانیکی روی بام است', 'مخزن و پمپ روی بام است', 'آسانسور/خرپشته و تجهیزات مرتبط روی بام است'],
    'language': ['توضیحات فارسی و تگ‌های فنی لاتین', 'کاملاً فارسی', 'کاملاً انگلیسی', 'فارسی و انگلیسی'],
    'supply': ['همه واحدها تک‌فاز', 'واحدها تک‌فاز و مشاعات سه‌فاز', 'همه انشعاب‌ها سه‌فاز', 'ترکیبی بر اساس نوع مصرف'],
    'main_panel': ['همکف نزدیک ورودی اصلی', 'پارکینگ یا زیرزمین', 'اتاق برق مستقل', 'محل در پلان مشخص شده است'],
    'emergency': ['نیاز نداریم', 'ژنراتور', 'UPS', 'ژنراتور و UPS'],
    'elevator': ['آسانسور نداریم', 'یک آسانسور مسافربر', 'دو یا چند آسانسور', 'آسانسور مسافربر و باربر/خودروبر'],
    'loads': ['مصارف متعارف واحدهای مسکونی', 'پمپ آب و تجهیزات مکانیکی مشترک', 'تجهیزات سرمایش و گرمایش برقی', 'بارهای تجاری یا صنعتی ویژه'],
    'lighting': ['روشنایی متعارف با کلیدهای معمولی', 'سنسور حضور برای مشاعات', 'دیمر و سناریوی روشنایی', 'سیستم هوشمند ساختمان'],
    'power': ['پریزهای متعارف مطابق ضوابط', 'پریزهای متعارف به‌همراه مدارهای اختصاصی آشپزخانه', 'مصارف قدرت و سه‌فاز داریم', 'جانمایی پریزها در پلان مشخص شده است'],
    'elv': ['آنتن، تلفن و شبکه', 'آنتن، تلفن، شبکه و آیفون', 'سیستم کامل جریان ضعیف و دوربین مداربسته', 'فقط زیرساخت و لوله‌گذاری'],
    'fire_alarm': ['اعلام حریق متعارف مستقل', 'سیستم متعارف زون‌بندی‌شده', 'سیستم آدرس‌پذیر', 'طبق نظر آتش‌نشانی تعیین شود'],
    'earthing': ['چاه ارت و هم‌بندی اصلی', 'سیستم ارت فونداسیون', 'ارت مشترک به‌همراه هم‌بندی کامل', 'طبق گزارش خاک و نظر مشاور تعیین شود'],
    'heating': ['پکیج دیواری و رادیاتور', 'موتورخانه مرکزی و رادیاتور', 'گرمایش از کف', 'سیستم هیت‌پمپ/فن‌کویل'],
    'cooling': ['کولر آبی', 'اسپلیت یا داکت‌اسپلیت', 'چیلر و فن‌کویل', 'VRF/VRV'],
    'gas': ['ساختمان گاز ندارد', 'گاز برای پکیج و اجاق هر واحد', 'گاز مرکزی برای موتورخانه', 'محل ورود و کنتورها در پلان مشخص است'],
    'water': ['ورود مستقیم آب شهری بدون مخزن و پمپ', 'مخزن و پمپ در زیرزمین/پارکینگ', 'مخزن و پمپ روی بام', 'محل ورود، مخزن و پمپ در پلان مشخص است'],
    'sanitary': ['اتصال به شبکه فاضلاب شهری', 'چاه جذبی', 'سپتیک یا تصفیه‌خانه محلی', 'محل خروج در پلان مشخص است'],
    'ventilation': ['همه فضاها به نما یا شفت دسترسی دارند', 'سرویس‌ها نیازمند اگزاست مکانیکی‌اند', 'پارکینگ نیازمند تهویه مکانیکی است', 'سرویس‌ها و پارکینگ هر دو تهویه مکانیکی می‌خواهند'],
    'plumbing': ['لوله پنج‌لایه کلکتوری', 'لوله پلیمری انشعابی', 'لوله فلزی', 'نوع لوله را طراح پیشنهاد دهد'],
    'drainage': ['فاضلاب و ونت متعارف ثقلی', 'سیستم فاضلاب کم‌صدا', 'محدودیت جدی برای شیب یا عبور لوله داریم', 'مسیرها و رایزرها در پلان مشخص شده‌اند'],
    'hvac': ['تجهیزات داخل هر واحد جانمایی شوند', 'تجهیزات روی بام جانمایی شوند', 'تجهیزات در موتورخانه یا فضای تأسیساتی هستند', 'محل تجهیزات در پلان مشخص شده است'],
    'parking': ['پارکینگ باز و دارای تهویه طبیعی', 'پارکینگ بسته با تهویه مکانیکی', 'پارکینگ نیمه‌باز', 'وضعیت تهویه طبق ضوابط محلی تعیین شود'],
}

TEXT_QUESTION_KEYS = {'location'}

def present_question(item):
    question = dict(item or {})
    key = question.get('key')
    question['input_type'] = 'text' if key in TEXT_QUESTION_KEYS else 'radio'
    question['options'] = list(QUESTION_OPTIONS.get(key, []))
    return question

def qlist(items): return [present_question({'key':k,'question':q}) for k,q in items]

BLOG = [
{'slug':'electrical-building-plan','title':'نقشه برق ساختمان؛ راهنمای طراحی تأسیسات برقی از پلان تا رایزر','excerpt':'راهنمای کاربردی طراحی پلان روشنایی، پریز و قدرت، اعلام حریق، جریان ضعیف، رایزر، تابلو برق و کنترل نهایی نقشه.','tag':'برق','body':[]},
{'slug':'mep-input-guide','title':'فایل معماری مناسب برای طراحی تأسیسات چه ویژگی‌هایی دارد؟','excerpt':'چک‌لیست آماده‌سازی DXF برای تحلیل دقیق‌تر لایه‌ها، ترازها و شفت‌ها.','tag':'راهنما','body':['برای شروع طراحی، فایل معماری باید خوانا، مقیاس‌پذیر و فاقد فایل‌های نامرتبط باشد.','پلان‌های ترازهای متفاوت را جدا نگه دارید و نام فضاها، شفت‌ها، بازشوها و اطلاعات اصلی را حذف نکنید.','اگر چند DXF دارید، آن‌ها را در یک ZIP قرار دهید؛ فایل‌های مخفی سیستم به‌صورت خودکار نادیده گرفته می‌شوند.']},
{'slug':'electrical-plan-scope','title':'تفاوت پلان روشنایی، قدرت، اعلام حریق و جریان ضعیف','excerpt':'چرا یک نقشه برق ممکن است به چند شیت تخصصی تقسیم شود؟','tag':'برق','body':['نقشه برق فقط یک پلان واحد نیست؛ Scope می‌تواند شامل روشنایی، پریز و قدرت، اعلام حریق، جریان ضعیف، ارت و تابلوها باشد.','اگر تراکم اطلاعات خوانایی را کاهش دهد، هر Level باید به چند شیت سیستمی تفکیک شود.','تعداد پلان‌های پایه از Levelهای معماری می‌آید و رایزر، SLD و Panel Schedule جدا از آن محاسبه می‌شوند.']},
{'slug':'mechanical-plan-scope','title':'از آب و فاضلاب تا HVAC؛ Scope نقشه‌های مکانیکی','excerpt':'مرور سیستم‌های اصلی مکانیک و نحوه تفکیک خروجی‌ها.','tag':'مکانیک','body':['در طراحی مکانیک، آب سرد و گرم، فاضلاب و ونت، گاز، گرمایش، سرمایش و تهویه هرکدام Scope مستقل دارند.','تعداد پلان‌های طبقه‌ای بر اساس Levelهای معماری تعیین می‌شود و در صورت نیاز رایزرها و دیتیل‌ها به آن اضافه می‌شوند.','هدف نهایی حفظ خوانایی، قابلیت اجرا و تطابق با اطلاعات واقعی پروژه است.']}]

app = FastAPI(title='EngiTools')
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site='lax')
app.mount('/static', StaticFiles(directory='app/static'), name='static')
templates = Jinja2Templates(directory='app/templates')

def current_user(request):
    uid=request.session.get('uid')
    if uid:
        db=Session(); u=db.get(User,uid); db.close()
        if u:return u
    db=Session(); u=User(email=f'anon-{uuid.uuid4().hex}@local'); db.add(u); db.commit(); db.refresh(u); request.session['uid']=u.id; db.close(); return u

def own_project(pid,uid):
    db=Session(); p=db.get(Project,pid)
    if not p or p.user_id!=uid: db.close(); return None,None
    return db,p

def is_real_dxf_path(path): return path.suffix.lower()=='.dxf' and '__MACOSX' not in path.parts and not path.name.startswith('.') and not path.name.startswith('._')

def analyze_dxf(path):
    recovery=normalize_input_copy(path); doc,_=read_input_dxf(path); msp=doc.modelspace(); counts=Counter(e.dxftype() for e in msp); texts=[]
    for e in msp:
        try:
            if e.dxftype()=='TEXT' and e.dxf.text.strip(): texts.append(e.dxf.text.strip())
            elif e.dxftype()=='MTEXT' and e.plain_text().strip(): texts.append(e.plain_text().strip())
        except Exception: pass
    return {'file':path.name,'version':doc.dxfversion,'insunits':int(doc.header.get('$INSUNITS',0) or 0),'layers':[l.dxf.name for l in doc.layers],'entities':dict(counts),'texts':texts[:200],'recovery':recovery}

def safe_extract(zip_path,dest):
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            out=(dest/info.filename).resolve()
            if not str(out).startswith(str(dest.resolve())): raise ValueError('مسیر نامعتبر داخل ZIP')
        z.extractall(dest)

def save_project_input(project_id,file):
    name=file.filename or ''; ext=Path(name).suffix.lower()
    if ext not in {'.zip','.dxf'}: raise ValueError('فقط فایل DXF یا ZIP شامل DXF مجاز است.')
    pdir=DATA_DIR/'projects'/str(project_id); pdir.mkdir(parents=True,exist_ok=True)
    for old in (pdir/'architecture.zip',pdir/'architecture.dxf'):
        if old.exists(): old.unlink()
    target=pdir/('architecture.zip' if ext=='.zip' else 'architecture.dxf')
    with target.open('wb') as f: shutil.copyfileobj(file.file,f)
    return target

def analyze_project_job(project_id):
    db=Session(); p=db.get(Project,project_id)
    if not p: db.close(); return
    try:
        pdir=DATA_DIR/'projects'/str(project_id); inp=pdir/'input'; shutil.rmtree(inp,ignore_errors=True); inp.mkdir(parents=True,exist_ok=True)
        z,d=pdir/'architecture.zip',pdir/'architecture.dxf'
        if z.exists(): safe_extract(z,inp)
        elif d.exists(): shutil.copy2(d,inp/d.name)
        else: raise ValueError('فایل ورودی پروژه پیدا نشد.')
        files=sorted(x for x in inp.rglob('*.dxf') if is_real_dxf_path(x))
        if not files: raise ValueError('هیچ فایل DXF معتبر پیدا نشد.')
        discipline=(p.answers or {}).get('discipline','mechanical')
        p.analysis={'discipline':discipline,'file_count':len(files),'files':[analyze_dxf(x) for x in files]}
        p.status='asking'; p.current_question=0; p.answers={'discipline':discipline}; p.last_error=''; db.commit()
    except Exception as e: p.status='awaiting_upload'; p.last_error=str(e); db.commit()
    finally: db.close()

def schedule_analysis(project_id):
    """Scheduling hook replaced by the persistent queue in production."""
    threading.Thread(target=analyze_project_job,args=(project_id,),daemon=True).start()

def run_design(project_id,revision_id):
    db=Session(); p=db.get(Project,project_id); r=db.get(Revision,revision_id)
    try:
        p.status='designing'; r.status='processing'; db.commit()
        if not CAD_DESIGNER_URL: raise RuntimeError('موتور CAD Designer هنوز به این سرویس متصل نشده است.')
        pdir=DATA_DIR/'projects'/str(p.id); discipline=(p.answers or {}).get('discipline',(p.analysis or {}).get('discipline','mechanical'))
        if discipline not in OUTPUT_SCOPES: raise RuntimeError('رشته پروژه معتبر نیست.')
        scope=OUTPUT_SCOPES[discipline]
        design_answers = dict(p.answers or {})
        if discipline == 'mechanical':
            drawing_set = (p.analysis or {}).get('drawing_set') or {}
            approved_manifest = drawing_set.get('approved_manifest')
            if not approved_manifest:
                raise RuntimeError('Approved mechanical drawing manifest is missing from the project workflow.')
            design_answers['_approved_drawing_manifest'] = approved_manifest
        payload={'project_id':str(p.id),'discipline':discipline,'architecture_dir':str(pdir/'input'),'answers':design_answers,'plan_analysis':p.analysis,'rulebook_path':RULEBOOK_PATH,'revision':r.revision_no,'revision_instructions':r.feedback,'output_scope':{'discipline':discipline,'label':scope['label'],'systems':scope['systems'],'only_this_discipline':True,'include_other_disciplines':False}}
        resp=requests.post(CAD_DESIGNER_URL+'/design',json=payload,timeout=3600)
        if not resp.ok:
            try: detail=resp.json().get('detail')
            except Exception: detail=''
            translations={
                'floor heights / false-ceiling constraints':'ارتفاع طبقات یا سقف کاذب',
                'water inlet pressure':'فشار واقعی آب ورودی',
                'fixture_and_symbol_traceability':'تأیید تعداد تجهیزات بهداشتی',
                'roof_drainage_design':'تأیید مشخصات بام و کف‌خواب‌ها',
            }
            message=str(detail or 'موتور طراحی اطلاعات پروژه را کافی تشخیص نداد.')
            for source,target in translations.items(): message=message.replace(source,target)
            raise RuntimeError('طراحی متوقف شد: '+message)
        data=resp.json()
        returned_discipline=data.get('discipline')
        if returned_discipline and returned_discipline!=discipline: raise RuntimeError('خروجی CAD Designer با رشته انتخاب‌شده پروژه تطابق ندارد.')
        src=Path(data['pdf_path']); out=pdir/'output'/f'rev_{r.revision_no:03d}'; out.mkdir(parents=True,exist_ok=True); dst=out/f'{discipline}_design.pdf'; shutil.copy2(src,dst)
        r.pdf_path=str(dst); r.status='ready'; p.status='ready'; p.current_revision=r.revision_no; p.last_error=''; db.commit()
    except Exception as e:
        error = str(e)
        r.status = 'failed'; r.error = error
        fixture_answer = str((p.answers or {}).get('fixture_schedule') or '')
        normalized_fixture_answer = fixture_answer.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
        fixture_is_quantified = bool(re.search(r'\d+', normalized_fixture_answer)) and any(
            token in normalized_fixture_answer.lower()
            for token in ('sink', 'faucet', 'toilet', 'bath', 'shower', 'سینک', 'روشویی', 'روشويی', 'توالت', 'دوش', 'وان')
        )
        evidence_failure = (
            discipline == 'mechanical'
            and ('fixture_and_symbol_traceability' in error or 'تعداد و جانمایی تجهیزات بهداشتی' in error)
            and not fixture_is_quantified
        )
        fixture_index = next(
            (index for index, question in enumerate(p.questions or []) if question.get('key') == 'fixture_schedule'),
            None,
        )
        if evidence_failure and fixture_index is not None:
            # Do not strand the user at a terminal QA error when the only
            # missing evidence is the quantitative answer we should have
            # validated earlier. Return to that exact question in-place.
            p.current_question = fixture_index
            p.status = 'asking'
            p.last_error = (
                'تعداد تجهیزات بهداشتی باید به‌صورت عددی وارد شود؛ '
                'مثال: سینک ۲، روشویی ۲، توالت ۲، دوش ۰.'
            )
        else:
            p.status = 'failed'; p.last_error = error
        db.commit()
    finally: db.close()

def flow_payload(p):
    questions=p.questions or []; idx=p.current_question or 0; discipline=(p.answers or {}).get('discipline',(p.analysis or {}).get('discipline','mechanical')); cfg=DISCIPLINES.get(discipline,DISCIPLINES['mechanical']); current=present_question(questions[idx]) if idx<len(questions) else None
    return {'project_id':p.id,'name':p.name,'status':p.status,'discipline':discipline,'discipline_title':cfg['title'],'error':p.last_error or '','question_count':len(questions),'current_index':idx,'progress':round((idx*100/len(questions)),1) if questions else 100,'question':current,'ready_to_design':p.status=='ready_to_design','current_revision':p.current_revision or 0,'pdf_url':f'/projects/{p.id}/pdf/{p.current_revision}' if p.status=='ready' and p.current_revision else None}

@app.get('/health')
def health(): return {'ok':True}
@app.get('/system_health')
def system_health():
    cad={'configured':bool(CAD_DESIGNER_URL),'reachable':False}
    if CAD_DESIGNER_URL:
        try: cad['reachable']=requests.get(CAD_DESIGNER_URL+'/health',timeout=3).ok
        except Exception: pass
    return {'status':'ok','cad_designer':cad,'rulebook_exists':Path(RULEBOOK_PATH).exists()}
@app.get('/sitemap.xml')
def sitemap(request:Request):
    scheme=request.headers.get('x-forwarded-proto','https').split(',')[0].strip(); base=f'{scheme}://{request.url.netloc}'; paths=['/','/electrical','/mechanical','/blog']+[f"/blog/{p['slug']}" for p in BLOG]; rows=''.join(f'<url><loc>{base}{path}</loc><changefreq>{"weekly" if path.startswith("/blog/") else "daily"}</changefreq><priority>{"0.8" if path.startswith("/blog/") else "0.9"}</priority></url>' for path in paths); xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+rows+'</urlset>'; return Response(content=xml,media_type='application/xml')
@app.get('/robots.txt')
def robots(request:Request):
    scheme=request.headers.get('x-forwarded-proto','https').split(',')[0].strip(); base=f'{scheme}://{request.url.netloc}'; return Response(content=f'User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n',media_type='text/plain')
@app.get('/{indexnow_key}.txt')
def indexnow_key_file(indexnow_key:str):
    if not INDEXNOW_KEY or indexnow_key!=INDEXNOW_KEY: raise HTTPException(404)
    return Response(content=INDEXNOW_KEY,media_type='text/plain')
@app.get('/',response_class=HTMLResponse)
def home(request:Request): return templates.TemplateResponse('dashboard.html',{'request':request,'blog':BLOG})
@app.get('/mechanical',response_class=HTMLResponse)
def mechanical(request:Request): return templates.TemplateResponse('discipline.html',{'request':request,'discipline':'mechanical','cfg':DISCIPLINES['mechanical']})
@app.get('/electrical',response_class=HTMLResponse)
def electrical(request:Request): return templates.TemplateResponse('discipline.html',{'request':request,'discipline':'electrical','cfg':DISCIPLINES['electrical']})
@app.get('/architect',response_class=HTMLResponse)
def architect(request:Request): return templates.TemplateResponse('architect.html',{'request':request})
@app.get('/blog',response_class=HTMLResponse)
def blog(request:Request): return templates.TemplateResponse('blog.html',{'request':request,'posts':BLOG})
@app.get('/blog/{slug}',response_class=HTMLResponse)
def article(slug:str,request:Request):
    post=next((x for x in BLOG if x['slug']==slug),None)
    if not post: raise HTTPException(404)
    if slug=='electrical-building-plan': return templates.TemplateResponse('electrical_building_plan.html',{'request':request,'post':post})
    return templates.TemplateResponse('article.html',{'request':request,'post':post})
@app.post('/start-project/{discipline}')
def start_project_discipline(discipline:str,request:Request,name:str=Form(''),file:UploadFile=File(...)):
    if discipline not in DISCIPLINES: raise HTTPException(404)
    u=current_user(request); db=Session(); project_name=(name or '').strip() or f"{DISCIPLINES[discipline]['title']} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"; p=Project(user_id=u.id,name=project_name,questions=qlist(DISCIPLINES[discipline]['questions']),answers={'discipline':discipline},status='uploading'); db.add(p); db.commit(); db.refresh(p)
    try: save_project_input(p.id,file); p.status='analyzing'; p.last_error=''; db.commit(); pid=p.id; schedule_analysis(pid)
    except Exception as e: p.last_error=str(e); p.status='awaiting_upload'; db.commit(); pid=p.id
    db.close(); url=f'/projects/{pid}'
    if request.headers.get('x-requested-with')=='XMLHttpRequest': return JSONResponse({'ok':True,'project_id':pid,'status_url':f'/projects/{pid}/status','flow_url':f'/projects/{pid}/flow','fallback_url':url})
    return RedirectResponse(url,303)
@app.post('/start-project')
def legacy_start(request:Request,name:str=Form(''),file:UploadFile=File(...),discipline:str=Form('mechanical')): return start_project_discipline(discipline,request,name,file)
@app.get('/projects/{pid}',response_class=HTMLResponse)
def project_page(pid:int,request:Request):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    revisions=db.query(Revision).filter(Revision.project_id==p.id).order_by(Revision.revision_no.desc()).all(); q=p.questions or []; current_question=present_question(q[p.current_question]) if p.current_question<len(q) else None; discipline=(p.answers or {}).get('discipline',(p.analysis or {}).get('discipline','mechanical')); cfg=DISCIPLINES.get(discipline,DISCIPLINES['mechanical']); response=templates.TemplateResponse('project.html',{'request':request,'p':p,'revisions':revisions,'current_question':current_question,'question_count':len(q),'discipline':discipline,'cfg':cfg}); db.close(); return response
@app.get('/projects/{pid}/status')
def project_status(pid:int,request:Request):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    data={'status':p.status,'error':p.last_error or '','analysis_count':(p.analysis or {}).get('file_count',0)}; db.close(); return data
@app.get('/projects/{pid}/flow')
def project_flow(pid:int,request:Request):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    data=flow_payload(p); db.close(); return JSONResponse(data)
@app.post('/projects/{pid}/upload')
def upload(pid:int,request:Request,file:UploadFile=File(...)):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    try: save_project_input(p.id,file); p.status='analyzing'; p.last_error=''; db.commit(); schedule_analysis(pid)
    except Exception as e: p.last_error=str(e); p.status='awaiting_upload'; db.commit()
    db.close()
    if request.headers.get('x-requested-with')=='XMLHttpRequest': return JSONResponse({'ok':True,'flow_url':f'/projects/{pid}/flow','fallback_url':f'/projects/{pid}'})
    return RedirectResponse(f'/projects/{pid}',303)
@app.post('/projects/{pid}/answer')
def answer(pid:int,request:Request,answer:str=Form(...)):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    qs=p.questions or []; idx=p.current_question
    if idx<len(qs): a=dict(p.answers or {}); a[qs[idx]['key']]=answer; p.answers=a; p.current_question=idx+1; p.status='ready_to_design' if p.current_question>=len(qs) else 'asking'; db.commit()
    db.close(); return RedirectResponse(f'/projects/{pid}',303)
@app.post('/projects/{pid}/answer-json')
def answer_json(pid:int,request:Request,answer:str=Form(...)):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    qs=p.questions or []; idx=p.current_question
    if p.status!='asking' or idx>=len(qs): data=flow_payload(p); db.close(); return JSONResponse(data)
    a=dict(p.answers or {}); a[qs[idx]['key']]=answer.strip(); p.answers=a; p.current_question=idx+1; p.status='ready_to_design' if p.current_question>=len(qs) else 'asking'; db.commit(); db.refresh(p); data=flow_payload(p); db.close(); return JSONResponse(data)
@app.post('/projects/{pid}/design')
def design(pid:int,request:Request):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    rev_no=(p.current_revision or 0)+1; r=Revision(project_id=p.id,revision_no=rev_no,status='queued'); db.add(r); p.status='queued'; db.commit(); db.refresh(r); rid=r.id; db.close(); threading.Thread(target=run_design,args=(pid,rid),daemon=True).start(); return RedirectResponse(f'/projects/{pid}',303)
@app.post('/projects/{pid}/design-json')
def design_json(pid:int,request:Request):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    if p.status!='ready_to_design': data=flow_payload(p); db.close(); return JSONResponse(data,status_code=409)
    rev_no=(p.current_revision or 0)+1; r=Revision(project_id=p.id,revision_no=rev_no,status='queued'); db.add(r); p.status='queued'; db.commit(); db.refresh(r); rid=r.id; data=flow_payload(p); db.close(); threading.Thread(target=run_design,args=(pid,rid),daemon=True).start(); return JSONResponse(data)
@app.post('/projects/{pid}/feedback')
def feedback(pid:int,request:Request,feedback:str=Form(...)):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    if any(x in feedback for x in ['همه پروژه','همیشه','باید در تمام','رول بوک','Rulebook']): db.add(RuleCandidate(project_id=p.id,feedback=feedback,candidate_rule=feedback))
    rev_no=(p.current_revision or 0)+1; r=Revision(project_id=p.id,revision_no=rev_no,status='queued',feedback=feedback); db.add(r); p.status='queued'; db.commit(); db.refresh(r); rid=r.id; db.close(); threading.Thread(target=run_design,args=(pid,rid),daemon=True).start(); return RedirectResponse(f'/projects/{pid}',303)
@app.get('/projects/{pid}/pdf/{rev}')
def get_pdf(pid:int,rev:int,request:Request):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    r=db.query(Revision).filter(Revision.project_id==p.id,Revision.revision_no==rev).first(); db.close()
    if not r or r.status!='ready' or not r.pdf_path: raise HTTPException(404)
    discipline=(p.answers or {}).get('discipline',(p.analysis or {}).get('discipline','mechanical')); return FileResponse(r.pdf_path,media_type='application/pdf',filename=f'EngiTools_{discipline}_{pid}_R{rev}.pdf')
