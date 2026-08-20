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

QUESTIONS = [
    ('location', 'پروژه در کدام کشور و شهر قرار دارد؟'),
    ('occupancy', 'کاربری دقیق ساختمان چیست؟'),
    ('codes', 'مبنای طراحی کدام مقررات و استانداردهاست؟'),
    ('floors', 'تعداد طبقات، زیرزمین/پارکینگ و بام را دقیق بفرمایید.'),
    ('units', 'تعداد کل واحدها و تعداد واحد در هر طبقه چقدر است؟'),
    ('typical', 'کدام طبقات تیپ هستند و کدام پلان متفاوت دارند؟'),
    ('supply', 'برق واحدها تک‌فاز است یا سه‌فاز؟'),
    ('main_panel', 'محل کنتورها و تابلوهای اصلی کجاست؟'),
    ('emergency', 'ژنراتور، UPS یا برق اضطراری دارید؟'),
    ('elevator', 'آسانسور دارید؟ تعداد و مشخصات آن را اگر دارید بفرمایید.'),
    ('loads', 'بارهای خاص برق مثل کولر، پکیج، پمپ، لباسشویی، ظرفشویی و ... را بفرمایید.'),
    ('elv', 'سیستم‌های جریان ضعیف موردنیاز را مشخص کنید.'),
    ('heating', 'سیستم گرمایش چیست؟'),
    ('cooling', 'سیستم سرمایش چیست؟'),
    ('gas', 'ساختمان گاز دارد؟ محل ورود گاز و تجهیزات گازسوز را بفرمایید.'),
    ('water', 'محل ورود آب، مخزن و پمپ مشخص است؟'),
    ('sanitary', 'خروج فاضلاب/چاه/شبکه شهری مشخص است؟'),
    ('ventilation', 'سرویس‌ها، آشپزخانه و پارکینگ به نما/شفت تهویه دسترسی دارند؟'),
    ('heights', 'ارتفاع طبقات، عمق و نوع سقف کاذب چقدر است؟'),
    ('shafts', 'شفت‌ها و رایزرها قطعی هستند یا اجازه پیشنهاد داریم؟'),
    ('roof', 'روی بام چه تجهیزاتی دارید؟'),
    ('parking', 'پارکینگ بسته است یا باز؟'),
    ('language', 'زبان خروجی را مشخص کنید. پیشنهاد: توضیحات فارسی و Tagهای فنی لاتین.')
]
QUESTION_LIST = [{'key': k, 'question': q} for k, q in QUESTIONS]

app = FastAPI(title='EngiTools MEP')
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site='lax')
app.mount('/static', StaticFiles(directory='app/static'), name='static')
templates = Jinja2Templates(directory='app/templates')

def current_user(request: Request):
    uid = request.session.get('uid')
    if uid:
        db = Session(); u = db.get(User, uid); db.close()
        if u: return u
    db = Session(); token = uuid.uuid4().hex
    u = User(email=f'anon-{token}@local', password_hash='anonymous')
    db.add(u); db.commit(); db.refresh(u); request.session['uid'] = u.id; db.close()
    return u

def own_project(pid: int, uid: int):
    db = Session(); p = db.get(Project, pid)
    if not p or p.user_id != uid:
        db.close(); return None, None
    return db, p

def is_real_dxf_path(path: Path) -> bool:
    return path.suffix.lower() == '.dxf' and '__MACOSX' not in path.parts and not path.name.startswith('.') and not path.name.startswith('._')

def analyze_dxf(path: Path):
    doc = ezdxf.readfile(path); msp = doc.modelspace(); counts = Counter(e.dxftype() for e in msp); texts = []
    for e in msp:
        try:
            if e.dxftype() == 'TEXT' and e.dxf.text.strip(): texts.append(e.dxf.text.strip())
            elif e.dxftype() == 'MTEXT' and e.plain_text().strip(): texts.append(e.plain_text().strip())
        except Exception: pass
    return {'file': path.name, 'version': doc.dxfversion, 'insunits': int(doc.header.get('$INSUNITS', 0) or 0), 'layers': [l.dxf.name for l in doc.layers], 'entities': dict(counts), 'texts': texts[:200]}

def safe_extract(zip_path: Path, target: Path):
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        if not members: raise ValueError('ZIP خالی است.')
        useful, bad = [], []
        for m in members:
            parts = Path(m.filename).parts; name = Path(m.filename).name
            if '__MACOSX' in parts or name.startswith('.') or name.startswith('._'): continue
            if Path(m.filename).suffix.lower() != '.dxf': bad.append(m.filename)
            else: useful.append(m)
        if bad: raise ValueError('داخل ZIP فقط فایل DXF مجاز است. فایل غیرمجاز: ' + ', '.join(bad[:5]))
        if not useful: raise ValueError('هیچ فایل DXF معتبر داخل ZIP پیدا نشد.')
        for m in useful:
            dest = (target / m.filename).resolve()
            if not str(dest).startswith(str(target.resolve())): raise ValueError('ساختار ZIP نامعتبر است.')
            z.extract(m, target)

def save_project_input(project_id: int, file: UploadFile):
    if not file.filename:
        raise ValueError('فایل ورودی انتخاب نشده است.')
    ext = Path(file.filename).suffix.lower()
    if ext not in ('.zip', '.dxf'):
        raise ValueError('فایل ورودی باید DXF یا ZIP شامل فایل‌های DXF باشد.')
    pdir = DATA_DIR / 'projects' / str(project_id)
    pdir.mkdir(parents=True, exist_ok=True)
    # remove stale input payloads so re-upload cannot mix file types
    for old in (pdir / 'architecture.zip', pdir / 'architecture.dxf'):
        if old.exists(): old.unlink()
    target = pdir / ('architecture.zip' if ext == '.zip' else 'architecture.dxf')
    with target.open('wb') as f: shutil.copyfileobj(file.file, f)
    return target

def analyze_project_job(project_id: int):
    db = Session(); p = db.get(Project, project_id)
    if not p: db.close(); return
    try:
        pdir = DATA_DIR / 'projects' / str(project_id); inp = pdir / 'input'
        shutil.rmtree(inp, ignore_errors=True); inp.mkdir(parents=True, exist_ok=True)
        zip_path, dxf_path = pdir / 'architecture.zip', pdir / 'architecture.dxf'
        if zip_path.exists():
            safe_extract(zip_path, inp)
        elif dxf_path.exists():
            shutil.copy2(dxf_path, inp / dxf_path.name)
        else:
            raise ValueError('فایل ورودی پروژه پیدا نشد.')
        files = sorted(x for x in inp.rglob('*.dxf') if is_real_dxf_path(x))
        if not files: raise ValueError('هیچ فایل DXF معتبر پیدا نشد.')
        p.analysis = {'file_count': len(files), 'files': [analyze_dxf(x) for x in files]}
        p.status = 'asking'; p.current_question = 0; p.answers = {}; p.last_error = ''; db.commit()
    except Exception as e:
        p.status = 'awaiting_upload'; p.last_error = str(e); db.commit()
    finally: db.close()

def run_design(project_id: int, revision_id: int):
    db = Session(); p = db.get(Project, project_id); r = db.get(Revision, revision_id)
    try:
        p.status='designing'; r.status='processing'; db.commit()
        if not CAD_DESIGNER_URL: raise RuntimeError('موتور CAD Designer هنوز به این سرویس متصل نشده است.')
        pdir = DATA_DIR / 'projects' / str(p.id)
        payload = {'project_id': str(p.id), 'architecture_dir': str(pdir/'input'), 'answers': p.answers, 'plan_analysis': p.analysis, 'rulebook_path': RULEBOOK_PATH, 'revision': r.revision_no, 'revision_instructions': r.feedback}
        resp = requests.post(CAD_DESIGNER_URL + '/design', json=payload, timeout=3600); resp.raise_for_status(); data = resp.json()
        src = Path(data['pdf_path']); out = pdir/'output'/f'rev_{r.revision_no:03d}'; out.mkdir(parents=True, exist_ok=True); dst = out/'design.pdf'; shutil.copy2(src,dst)
        r.pdf_path=str(dst); r.status='ready'; p.status='ready'; p.current_revision=r.revision_no; p.last_error=''; db.commit()
    except Exception as e:
        r.status='failed'; r.error=str(e); p.status='failed'; p.last_error=str(e); db.commit()
    finally: db.close()

@app.get('/health')
def health(): return {'ok': True}

@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    u=current_user(request); db=Session(); projects=db.query(Project).filter(Project.user_id==u.id).order_by(Project.id.desc()).limit(6).all(); db.close()
    return templates.TemplateResponse('dashboard.html', {'request':request,'user':u,'projects':projects})

@app.post('/start-project')
def start_project(request: Request, name: str = Form(''), file: UploadFile = File(...)):
    u=current_user(request); db=Session(); project_name=(name or '').strip() or f'پروژه {datetime.now().strftime("%Y-%m-%d %H:%M")}'
    p=Project(user_id=u.id,name=project_name,questions=QUESTION_LIST,status='uploading'); db.add(p); db.commit(); db.refresh(p)
    try:
        save_project_input(p.id,file); p.status='analyzing'; p.last_error=''; db.commit(); pid=p.id; threading.Thread(target=analyze_project_job,args=(pid,),daemon=True).start()
    except Exception as e:
        p.last_error=str(e); p.status='awaiting_upload'; db.commit(); pid=p.id
    db.close(); url=f'/projects/{pid}'
    if request.headers.get('x-requested-with')=='XMLHttpRequest': return JSONResponse({'ok':True,'project_id':pid,'redirect':url})
    return RedirectResponse(url,303)

@app.post('/projects')
def new_project(request: Request, name: str = Form(...)):
    u=current_user(request); db=Session(); p=Project(user_id=u.id,name=name,questions=QUESTION_LIST,status='awaiting_upload'); db.add(p); db.commit(); db.refresh(p); pid=p.id; db.close(); return RedirectResponse(f'/projects/{pid}',303)

@app.get('/projects/{pid}', response_class=HTMLResponse)
def project_page(pid:int, request:Request):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    revisions=db.query(Revision).filter(Revision.project_id==p.id).order_by(Revision.revision_no.desc()).all(); q=p.questions or []; current_question=q[p.current_question] if p.current_question<len(q) else None
    response=templates.TemplateResponse('project.html',{'request':request,'user':u,'p':p,'revisions':revisions,'current_question':current_question,'question_count':len(q)}); db.close(); return response

@app.get('/projects/{pid}/status')
def project_status(pid:int, request:Request):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    data={'status':p.status,'error':p.last_error or '','analysis_count':(p.analysis or {}).get('file_count',0)}; db.close(); return data

@app.post('/projects/{pid}/upload')
def upload(pid:int, request:Request, file:UploadFile=File(...)):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    try:
        save_project_input(p.id,file); p.status='analyzing'; p.last_error=''; db.commit(); threading.Thread(target=analyze_project_job,args=(pid,),daemon=True).start()
    except Exception as e:
        p.last_error=str(e); p.status='awaiting_upload'; db.commit()
    db.close()
    if request.headers.get('x-requested-with')=='XMLHttpRequest': return JSONResponse({'ok':True,'redirect':f'/projects/{pid}'})
    return RedirectResponse(f'/projects/{pid}',303)

@app.post('/projects/{pid}/answer')
def answer(pid:int, request:Request, answer:str=Form(...)):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    qs=p.questions or []; idx=p.current_question
    if idx<len(qs):
        a=dict(p.answers or {}); a[qs[idx]['key']]=answer; p.answers=a; p.current_question=idx+1; p.status='ready_to_design' if p.current_question>=len(qs) else 'asking'; db.commit()
    db.close(); return RedirectResponse(f'/projects/{pid}',303)

@app.post('/projects/{pid}/design')
def design(pid:int, request:Request):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    rev_no=(p.current_revision or 0)+1; r=Revision(project_id=p.id,revision_no=rev_no,status='queued'); db.add(r); p.status='queued'; db.commit(); db.refresh(r); rid=r.id; db.close(); threading.Thread(target=run_design,args=(pid,rid),daemon=True).start(); return RedirectResponse(f'/projects/{pid}',303)

@app.post('/projects/{pid}/feedback')
def feedback(pid:int, request:Request, feedback:str=Form(...)):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    if any(x in feedback for x in ['همه پروژه','همیشه','باید در تمام','رول بوک','Rulebook']): db.add(RuleCandidate(project_id=p.id,feedback=feedback,candidate_rule=feedback))
    rev_no=(p.current_revision or 0)+1; r=Revision(project_id=p.id,revision_no=rev_no,status='queued',feedback=feedback); db.add(r); p.status='queued'; db.commit(); db.refresh(r); rid=r.id; db.close(); threading.Thread(target=run_design,args=(pid,rid),daemon=True).start(); return RedirectResponse(f'/projects/{pid}',303)

@app.get('/projects/{pid}/pdf/{rev}')
def get_pdf(pid:int, rev:int, request:Request):
    u=current_user(request); db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    r=db.query(Revision).filter(Revision.project_id==p.id,Revision.revision_no==rev).first(); db.close()
    if not r or r.status!='ready' or not r.pdf_path: raise HTTPException(404)
    return FileResponse(r.pdf_path,media_type='application/pdf',filename=f'MEP_Project_{pid}_R{rev}.pdf')
