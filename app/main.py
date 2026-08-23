import os, shutil, zipfile, threading, uuid
from pathlib import Path
from datetime import datetime
from collections import Counter

import requests, ezdxf
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
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
    ('location','پروژه در کدام کشور و شهر قرار دارد؟'),
    ('occupancy','کاربری دقیق ساختمان چیست؟'),
    ('codes','مبنای طراحی کدام مقررات و استانداردهاست؟'),
    ('floors','تعداد طبقات، زیرزمین/پارکینگ و بام را دقیق بفرمایید.'),
    ('units','تعداد کل واحدها و تعداد واحد در هر طبقه چقدر است؟'),
    ('typical','کدام طبقات تیپ هستند و کدام پلان متفاوت دارند؟'),
    ('heights','ارتفاع طبقات و وضعیت سقف کاذب را بفرمایید.'),
    ('shafts','شفت‌ها و رایزرهای موجود قطعی هستند یا اجازه پیشنهاد داریم؟'),
    ('roof','روی بام چه فضاها یا تجهیزاتی دارید؟'),
    ('language','زبان خروجی را مشخص کنید؛ پیشنهاد: توضیحات فارسی و Tagهای فنی لاتین.')
]
ELECTRICAL = [
    ('supply','برق واحدها تک‌فاز است یا سه‌فاز؟'),
    ('main_panel','محل کنتورها و تابلوهای اصلی کجاست؟'),
    ('emergency','ژنراتور، UPS یا برق اضطراری دارید؟'),
    ('elevator','آسانسور دارید؟ تعداد و مشخصات برق آن را بفرمایید.'),
    ('loads','بارهای خاص برق مثل کولر، پکیج، پمپ، لباسشویی و ظرفشویی را بفرمایید.'),
    ('lighting','نوع روشنایی و کنترل روشنایی مدنظر چیست؟'),
    ('power','پریزها و مصارف قدرت خاص چه نیازهایی دارند؟'),
    ('elv','سیستم‌های جریان ضعیف موردنیاز را مشخص کنید.'),
    ('fire_alarm','سیستم اعلام حریق چه Scope و زون‌بندی‌ای دارد؟'),
    ('earthing','الزامات ارت و هم‌بندی پروژه را بفرمایید.')
]
MECHANICAL = [
    ('heating','سیستم گرمایش چیست؟'),
    ('cooling','سیستم سرمایش چیست؟'),
    ('gas','ساختمان گاز دارد؟ محل ورود گاز و تجهیزات گازسوز را بفرمایید.'),
    ('water','محل ورود آب، مخزن و پمپ مشخص است؟'),
    ('sanitary','خروج فاضلاب/چاه/شبکه شهری مشخص است؟'),
    ('ventilation','سرویس‌ها، آشپزخانه و پارکینگ به نما/شفت تهویه دسترسی دارند؟'),
    ('plumbing','نوع لوله‌کشی آب سرد و گرم و محدودیت‌های اجرایی چیست؟'),
    ('drainage','الزامات فاضلاب، ونت و شیب‌بندی را بفرمایید.'),
    ('hvac','نوع تجهیزات HVAC و محل تقریبی آن‌ها مشخص است؟'),
    ('parking','پارکینگ بسته است یا باز و آیا تهویه مکانیکی لازم دارد؟')
]
DISCIPLINES = {
    'electrical': {'title':'همراه برق','subtitle':'طراحی تخصصی نقشه‌های برق ساختمان','icon':'⚡','questions':COMMON+ELECTRICAL,'accent':'electrical'},
    'mechanical': {'title':'همراه مکانیک','subtitle':'طراحی تخصصی نقشه‌های مکانیکی ساختمان','icon':'◉','questions':COMMON+MECHANICAL,'accent':'mechanical'}
}
OUTPUT_SCOPES = {
    'electrical': {
        'label': 'Electrical only',
        'systems': ['lighting','power','dedicated_loads','fire_alarm','elv','earthing_bonding','panels','single_line_diagram','electrical_risers','electrical_legend_notes']
    },
    'mechanical': {
        'label': 'Mechanical only',
        'systems': ['cold_water','hot_water','sanitary','vent','gas','heating_supply','heating_return','cooling','condensate','exhaust_ventilation','mechanical_risers','mechanical_details_legend_notes']
    }
}

def qlist(items):
    return [{'key':k,'question':q} for k,q in items]

BLOG = [
    {'slug':'mep-input-guide','title':'فایل معماری مناسب برای طراحی تأسیسات چه ویژگی‌هایی دارد؟','excerpt':'چک‌لیست آماده‌سازی DXF برای تحلیل دقیق‌تر لایه‌ها، ترازها و شفت‌ها.','tag':'راهنما','body':['برای شروع طراحی، فایل معماری باید خوانا، مقیاس‌پذیر و فاقد فایل‌های نامرتبط باشد.','پلان‌های ترازهای متفاوت را جدا نگه دارید و نام فضاها، شفت‌ها، بازشوها و اطلاعات اصلی را حذف نکنید.','اگر چند DXF دارید، آن‌ها را در یک ZIP قرار دهید؛ فایل‌های مخفی سیستم به‌صورت خودکار نادیده گرفته می‌شوند.']},
    {'slug':'electrical-plan-scope','title':'تفاوت پلان روشنایی، قدرت، اعلام حریق و جریان ضعیف','excerpt':'چرا یک نقشه برق ممکن است به چند شیت تخصصی تقسیم شود؟','tag':'برق','body':['نقشه برق فقط یک پلان واحد نیست؛ Scope می‌تواند شامل روشنایی، پریز و قدرت، اعلام حریق، جریان ضعیف، ارت و تابلوها باشد.','اگر تراکم اطلاعات خوانایی را کاهش دهد، هر Level باید به چند شیت سیستمی تفکیک شود.','تعداد پلان‌های پایه از Levelهای معماری می‌آید و رایزر، SLD و Panel Schedule جدا از آن محاسبه می‌شوند.']},
    {'slug':'mechanical-plan-scope','title':'از آب و فاضلاب تا HVAC؛ Scope نقشه‌های مکانیکی','excerpt':'مرور سیستم‌های اصلی مکانیک و نحوه تفکیک خروجی‌ها.','tag':'مکانیک','body':['در طراحی مکانیک، آب سرد و گرم، فاضلاب و ونت، گاز، گرمایش، سرمایش و تهویه هرکدام Scope مستقل دارند.','تعداد پلان‌های طبقه‌ای بر اساس Levelهای معماری تعیین می‌شود و در صورت نیاز رایزرها و دیتیل‌ها به آن اضافه می‌شوند.','هدف نهایی حفظ خوانایی، قابلیت اجرا و تطابق با اطلاعات واقعی پروژه است.']}
]

app = FastAPI(title='EngiTools')
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site='lax')
app.mount('/static', StaticFiles(directory='app/static'), name='static')
templates = Jinja2Templates(directory='app/templates')

def current_user(request):
    uid = request.session.get('uid')
    if uid:
        db = Session(); u = db.get(User, uid); db.close()
        if u: return u
    db = Session(); u = User(email=f'anon-{uuid.uuid4().hex}@local'); db.add(u); db.commit(); db.refresh(u); request.session['uid'] = u.id; db.close(); return u

def own_project(pid, uid):
    db = Session(); p = db.get(Project, pid)
    if not p or p.user_id != uid:
        db.close(); return None, None
    return db, p

def is_real_dxf_path(path):
    return path.suffix.lower()=='.dxf' and '__MACOSX' not in path.parts and not path.name.startswith('.') and not path.name.startswith('._')

def analyze_dxf(path):
    doc = ezdxf.readfile(path); msp = doc.modelspace(); counts = Counter(e.dxftype() for e in msp); texts = []
    for e in msp:
        try:
            if e.dxftype()=='TEXT' and e.dxf.text.strip(): texts.append(e.dxf.text.strip())
            elif e.dxftype()=='MTEXT' and e.plain_text().strip(): texts.append(e.plain_text().strip())
        except Exception: pass
    return {'file':path.name,'version':doc.dxfversion,'insunits':int(doc.header.get('$INSUNITS',0) or 0),'layers':[l.dxf.name for l in doc.layers],'entities':dict(counts),'texts':texts[:200]}

def safe_extract(zip_path, target):
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.infolist() if not m.is_dir()]; useful=[]; bad=[]
        if not members: raise ValueError('ZIP خالی است.')
        for m in members:
            parts=Path(m.filename).parts; name=Path(m.filename).name
            if '__MACOSX' in parts or name.startswith('.') or name.startswith('._'): continue
            (useful if Path(m.filename).suffix.lower()=='.dxf' else bad).append(m)
        if bad: raise ValueError('داخل ZIP فقط فایل DXF مجاز است.')
        if not useful: raise ValueError('هیچ فایل DXF معتبری در ZIP پیدا نشد.')
        for m in useful:
            dest=(target/m.filename).resolve()
            if not str(dest).startswith(str(target.resolve())): raise ValueError('مسیر فایل ZIP نامعتبر است.')
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(dest,'wb') as dst: shutil.copyfileobj(src,dst)

def persist_uploads(project_id, uploads):
    root=DATA_DIR/'projects'/str(project_id)/'input'; root.mkdir(parents=True,exist_ok=True); saved=[]
    for up in uploads:
        if not up or not up.filename: continue
        suffix=Path(up.filename).suffix.lower()
        if suffix not in {'.dxf','.zip'}: raise ValueError('فرمت مجاز DXF یا ZIP است.')
        dst=root/Path(up.filename).name
        with open(dst,'wb') as f: shutil.copyfileobj(up.file,f)
        if suffix=='.zip':
            ext=root/(dst.stem+'_unzipped'); ext.mkdir(exist_ok=True); safe_extract(dst,ext); saved += [p for p in ext.rglob('*') if p.is_file() and is_real_dxf_path(p)]
        else: saved.append(dst)
    if not saved: raise ValueError('حداقل یک DXF لازم است.')
    return saved

def build_questions(discipline):
    return qlist(DISCIPLINES[discipline]['questions'])

def generate_revision(project_id, revision_no):
    db=Session(); p=db.get(Project,project_id); r=db.query(Revision).filter_by(project_id=project_id,revision_no=revision_no).first()
    try:
        r.status='processing'; db.commit()
        if not CAD_DESIGNER_URL: raise RuntimeError('CAD_DESIGNER_URL تنظیم نشده است.')
        payload={'project_id':p.id,'revision_no':revision_no,'analysis':p.analysis,'answers':p.answers,'discipline':p.answers.get('_discipline'),'feedback':r.feedback,'rulebook_path':RULEBOOK_PATH,'output_scope':p.answers.get('_output_scope',{})}
        res=requests.post(f'{CAD_DESIGNER_URL}/generate',json=payload,timeout=180); res.raise_for_status(); data=res.json()
        pdf=data.get('pdf_path')
        if not pdf: raise RuntimeError('سرویس CAD مسیر PDF برنگرداند.')
        r.pdf_path=pdf; r.status='ready'; p.status='ready'; p.current_revision=revision_no
    except Exception as e:
        r.status='failed'; r.error=str(e); p.status='failed'; p.last_error=str(e)
    db.commit(); db.close()

def queue_revision(p, feedback=''):
    db=Session(); rev_no=p.current_revision+1; r=Revision(project_id=p.id,revision_no=rev_no,feedback=feedback,status='queued'); db.add(r); p.status='generating'; db.commit(); db.close(); threading.Thread(target=generate_revision,args=(p.id,rev_no),daemon=True).start()

@app.get('/system_health')
def health():
    cad={'configured':bool(CAD_DESIGNER_URL),'reachable':False}
    if CAD_DESIGNER_URL:
        try: cad['reachable']=requests.get(f'{CAD_DESIGNER_URL}/health',timeout=3).ok
        except Exception: pass
    return {'status':'ok','cad_designer':cad,'rulebook_exists':Path(RULEBOOK_PATH).exists()}

@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse('home.html', {'request':request,'blog':BLOG})

@app.get('/blog', response_class=HTMLResponse)
def blog(request: Request): return templates.TemplateResponse('blog.html',{'request':request,'posts':BLOG})

@app.get('/blog/{slug}', response_class=HTMLResponse)
def blog_post(request: Request, slug: str):
    post=next((x for x in BLOG if x['slug']==slug),None)
    if not post: raise HTTPException(404)
    return templates.TemplateResponse('blog_post.html',{'request':request,'post':post})

@app.get('/{discipline}', response_class=HTMLResponse)
def landing(request: Request, discipline: str):
    if discipline not in DISCIPLINES: raise HTTPException(404)
    return templates.TemplateResponse('landing.html',{'request':request,'discipline':discipline,'d':DISCIPLINES[discipline]})

@app.post('/{discipline}/start')
def start(request: Request, discipline: str, name: str=Form('پروژه جدید')):
    if discipline not in DISCIPLINES: raise HTTPException(404)
    u=current_user(request); db=Session(); answers={'_discipline':discipline,'_output_scope':OUTPUT_SCOPES[discipline]}; p=Project(user_id=u.id,name=name or 'پروژه جدید',questions=build_questions(discipline),answers=answers); db.add(p); db.commit(); db.refresh(p); pid=p.id; db.close(); return RedirectResponse(f'/project/{pid}/upload',303)

@app.get('/project/{pid}/upload', response_class=HTMLResponse)
def upload_page(request: Request,pid:int):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    d=p.answers.get('_discipline'); db.close(); return templates.TemplateResponse('upload.html',{'request':request,'p':p,'d':DISCIPLINES[d]})

@app.post('/project/{pid}/upload')
def upload(request: Request,pid:int, files:list[UploadFile]=File(...)):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    try:
        paths=persist_uploads(pid,files); p.analysis={'files':[analyze_dxf(x) for x in paths]}; p.status='questionnaire'; db.commit()
    except Exception as e:
        db.close(); return RedirectResponse(f'/project/{pid}/upload?error={requests.utils.quote(str(e))}',303)
    db.close(); return RedirectResponse(f'/project/{pid}/questions',303)

@app.get('/project/{pid}/questions', response_class=HTMLResponse)
def questions(request: Request,pid:int):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    if p.current_question>=len(p.questions): db.close(); return RedirectResponse(f'/project/{pid}/review',303)
    q=p.questions[p.current_question]; idx=p.current_question+1; total=len(p.questions); db.close(); return templates.TemplateResponse('questions.html',{'request':request,'p':p,'q':q,'idx':idx,'total':total})

@app.post('/project/{pid}/questions')
def answer(request: Request,pid:int, answer: str=Form(...)):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    if p.current_question<len(p.questions):
        q=p.questions[p.current_question]; a=dict(p.answers or {}); a[q['key']]=answer; p.answers=a; p.current_question+=1; db.commit()
    done=p.current_question>=len(p.questions); db.close(); return RedirectResponse(f'/project/{pid}/review' if done else f'/project/{pid}/questions',303)

@app.get('/project/{pid}/review', response_class=HTMLResponse)
def review(request: Request,pid:int):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    db.close(); return templates.TemplateResponse('review.html',{'request':request,'p':p})

@app.post('/project/{pid}/generate')
def generate(request: Request,pid:int):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    db.expunge(p); db.close(); queue_revision(p); return RedirectResponse(f'/project/{pid}/status',303)

@app.get('/project/{pid}/status', response_class=HTMLResponse)
def status(request: Request,pid:int):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    rev=db.query(Revision).filter_by(project_id=pid).order_by(Revision.revision_no.desc()).first(); db.close(); return templates.TemplateResponse('status.html',{'request':request,'p':p,'rev':rev})

@app.get('/project/{pid}/download')
def download(request: Request,pid:int):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    rev=db.query(Revision).filter_by(project_id=pid,revision_no=p.current_revision).first(); db.close()
    if not rev or rev.status!='ready': raise HTTPException(404)
    if rev.pdf_path.startswith('http://') or rev.pdf_path.startswith('https://'): return RedirectResponse(rev.pdf_path)
    path=Path(rev.pdf_path)
    if not path.exists(): raise HTTPException(404,'PDF در دسترس نیست.')
    return FileResponse(path,media_type='application/pdf',filename=f'EngiTools_{pid}_R{rev.revision_no}.pdf')

@app.post('/project/{pid}/revise')
def revise(request: Request,pid:int, feedback: str=Form(...)):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    db.add(RuleCandidate(project_id=pid,feedback=feedback,candidate_rule='نیازمند بازبینی و تبدیل به قانون عمومی در Rulebook')); db.commit(); db.expunge(p); db.close(); queue_revision(p,feedback); return RedirectResponse(f'/project/{pid}/status',303)
