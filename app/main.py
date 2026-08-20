import os, json, shutil, zipfile, threading
from pathlib import Path
from datetime import datetime
import requests, ezdxf
from collections import Counter
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, String, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from passlib.context import CryptContext

DATA_DIR = Path(os.getenv('DATA_DIR','/data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_URL = os.getenv('DATABASE_URL', f"sqlite:///{DATA_DIR/'mep.db'}")
RULEBOOK_PATH = os.getenv('RULEBOOK_PATH', str(DATA_DIR/'rulebook/MEP_Design_Rulebook.docx'))
CAD_DESIGNER_URL = os.getenv('CAD_DESIGNER_URL','').rstrip('/')
SESSION_SECRET = os.getenv('SESSION_SECRET','dev-secret-change-me')

connect_args = {'check_same_thread':False} if DB_URL.startswith('sqlite') else {}
engine = create_engine(DB_URL, connect_args=connect_args, pool_pre_ping=True)
Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
class Project(Base):
    __tablename__='projects'
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
    __tablename__='revisions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    revision_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default='queued')
    feedback: Mapped[str] = mapped_column(Text, default='')
    pdf_path: Mapped[str] = mapped_column(Text, default='')
    error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
class RuleCandidate(Base):
    __tablename__='rule_candidates'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer)
    feedback: Mapped[str] = mapped_column(Text)
    candidate_rule: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)
pwd = CryptContext(schemes=['bcrypt'], deprecated='auto')

QUESTIONS = [
('location','پروژه در کدام کشور و شهر قرار دارد؟'),('occupancy','کاربری دقیق ساختمان چیست؟'),('codes','مبنای طراحی کدام مقررات و استانداردهاست؟'),
('floors','تعداد طبقات، زیرزمین/پارکینگ و بام را دقیق بفرمایید.'),('units','تعداد کل واحدها و تعداد واحد در هر طبقه چقدر است؟'),
('typical','کدام طبقات تیپ هستند و کدام پلان متفاوت دارند؟'),('supply','برق واحدها تک‌فاز است یا سه‌فاز؟'),('main_panel','محل کنتورها و تابلوهای اصلی کجاست؟'),
('emergency','ژنراتور، UPS یا برق اضطراری دارید؟'),('elevator','آسانسور دارید؟ تعداد و مشخصات آن را اگر دارید بفرمایید.'),
('loads','بارهای خاص برق مثل کولر، پکیج، پمپ، لباسشویی، ظرفشویی و ... را بفرمایید.'),('elv','سیستم‌های جریان ضعیف موردنیاز را مشخص کنید.'),
('heating','سیستم گرمایش چیست؟'),('cooling','سیستم سرمایش چیست؟'),('gas','ساختمان گاز دارد؟ محل ورود گاز و تجهیزات گازسوز را بفرمایید.'),
('water','محل ورود آب، مخزن و پمپ مشخص است؟'),('sanitary','خروج فاضلاب/چاه/شبکه شهری مشخص است؟'),('ventilation','سرویس‌ها، آشپزخانه و پارکینگ به نما/شفت تهویه دسترسی دارند؟'),
('heights','ارتفاع طبقات، عمق و نوع سقف کاذب چقدر است؟'),('shafts','شفت‌ها و رایزرها قطعی هستند یا اجازه پیشنهاد داریم؟'),('roof','روی بام چه تجهیزاتی دارید؟'),
('parking','پارکینگ بسته است یا باز؟'),('language','زبان خروجی را مشخص کنید. پیشنهاد: توضیحات فارسی و Tagهای فنی لاتین.')]
QUESTION_LIST=[{'key':k,'question':q} for k,q in QUESTIONS]

app=FastAPI(title='MEP Designer')
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site='lax')
app.mount('/static', StaticFiles(directory='app/static'), name='static')
templates=Jinja2Templates(directory='app/templates')

def current_user(request):
    uid=request.session.get('uid')
    if not uid: return None
    db=Session(); u=db.get(User, uid); db.close(); return u

def own_project(pid, uid):
    db=Session(); p=db.get(Project,pid)
    if not p or p.user_id!=uid: db.close(); return None,None
    return db,p

def analyze_dxf(path):
    doc=ezdxf.readfile(path); msp=doc.modelspace(); counts=Counter(e.dxftype() for e in msp); texts=[]
    for e in msp:
        try:
            if e.dxftype()=='TEXT' and e.dxf.text.strip(): texts.append(e.dxf.text.strip())
            elif e.dxftype()=='MTEXT' and e.plain_text().strip(): texts.append(e.plain_text().strip())
        except: pass
    return {'file':path.name,'version':doc.dxfversion,'insunits':int(doc.header.get('$INSUNITS',0) or 0),'layers':[l.dxf.name for l in doc.layers],'entities':dict(counts),'texts':texts[:200]}

def safe_extract(zip_path,target):
    with zipfile.ZipFile(zip_path) as z:
        ms=[m for m in z.infolist() if not m.is_dir()]
        if not ms: raise ValueError('ZIP خالی است')
        bad=[m.filename for m in ms if Path(m.filename).suffix.lower()!='.dxf']
        if bad: raise ValueError('داخل ZIP فقط DXF مجاز است: '+', '.join(bad[:5]))
        for m in ms:
            dest=(target/m.filename).resolve()
            if not str(dest).startswith(str(target.resolve())): raise ValueError('ZIP نامعتبر است')
        z.extractall(target)

def run_design(project_id, revision_id):
    db=Session(); p=db.get(Project,project_id); r=db.get(Revision,revision_id)
    try:
        p.status='designing'; r.status='processing'; db.commit()
        if not CAD_DESIGNER_URL:
            raise RuntimeError('CAD_DESIGNER_URL هنوز تنظیم نشده است؛ موتور تولید نقشه باید متصل شود.')
        pdir=DATA_DIR/'projects'/str(p.id)
        payload={'project_id':str(p.id),'architecture_dir':str(pdir/'input'),'answers':p.answers,'plan_analysis':p.analysis,'rulebook_path':RULEBOOK_PATH,'revision':r.revision_no,'revision_instructions':r.feedback}
        resp=requests.post(CAD_DESIGNER_URL+'/design',json=payload,timeout=3600); resp.raise_for_status(); data=resp.json()
        src=Path(data['pdf_path']); out=pdir/'output'/f'rev_{r.revision_no:03d}'; out.mkdir(parents=True,exist_ok=True); dst=out/'design.pdf'; shutil.copy2(src,dst)
        r.pdf_path=str(dst); r.status='ready'; p.status='ready'; p.current_revision=r.revision_no; p.last_error=''; db.commit()
    except Exception as e:
        r.status='failed'; r.error=str(e); p.status='failed'; p.last_error=str(e); db.commit()
    finally: db.close()

@app.get('/health')
def health(): return {'ok':True}

@app.get('/', response_class=HTMLResponse)
def home(request:Request):
    u=current_user(request)
    if not u: return RedirectResponse('/login',303)
    db=Session(); ps=db.query(Project).filter(Project.user_id==u.id).order_by(Project.id.desc()).all(); db.close()
    return templates.TemplateResponse('dashboard.html',{'request':request,'user':u,'projects':ps})

@app.get('/login',response_class=HTMLResponse)
def login_page(request:Request): return templates.TemplateResponse('login.html',{'request':request,'mode':'login'})
@app.post('/login')
def login(request:Request,email:str=Form(...),password:str=Form(...)):
    db=Session(); u=db.query(User).filter(User.email==email).first()
    if not u or not pwd.verify(password,u.password_hash): db.close(); return templates.TemplateResponse('login.html',{'request':request,'mode':'login','error':'ایمیل یا رمز عبور اشتباه است'})
    request.session['uid']=u.id; db.close(); return RedirectResponse('/',303)
@app.get('/register',response_class=HTMLResponse)
def register_page(request:Request): return templates.TemplateResponse('login.html',{'request':request,'mode':'register'})
@app.post('/register')
def register(request:Request,email:str=Form(...),password:str=Form(...)):
    db=Session()
    if db.query(User).filter(User.email==email).first(): db.close(); return templates.TemplateResponse('login.html',{'request':request,'mode':'register','error':'این ایمیل قبلاً ثبت شده است'})
    u=User(email=email,password_hash=pwd.hash(password)); db.add(u); db.commit(); db.refresh(u); request.session['uid']=u.id; db.close(); return RedirectResponse('/',303)
@app.get('/logout')
def logout(request:Request): request.session.clear(); return RedirectResponse('/login',303)

@app.post('/projects')
def new_project(request:Request,name:str=Form(...)):
    u=current_user(request)
    if not u: return RedirectResponse('/login',303)
    db=Session(); p=Project(user_id=u.id,name=name,questions=QUESTION_LIST,status='awaiting_upload'); db.add(p); db.commit(); db.refresh(p); pid=p.id; db.close(); return RedirectResponse(f'/projects/{pid}',303)

@app.get('/projects/{pid}',response_class=HTMLResponse)
def project_page(pid:int,request:Request):
    u=current_user(request)
    if not u: return RedirectResponse('/login',303)
    db,p=own_project(pid,u.id)
    if not p: raise HTTPException(404)
    revs=db.query(Revision).filter(Revision.project_id==p.id).order_by(Revision.revision_no.desc()).all(); q=(p.questions or []); cq=q[p.current_question] if p.current_question<len(q) else None
    return templates.TemplateResponse('project.html',{'request':request,'user':u,'p':p,'revisions':revs,'current_question':cq,'question_count':len(q)})

@app.post('/projects/{pid}/upload')
def upload(pid:int,request:Request,file:UploadFile=File(...)):
    u=current_user(request); db,p=own_project(pid,u.id if u else -1)
    if not p: raise HTTPException(404)
    if not file.filename.lower().endswith('.zip'): db.close(); return RedirectResponse(f'/projects/{pid}?err=zip',303)
    pdir=DATA_DIR/'projects'/str(p.id); inp=pdir/'input'; shutil.rmtree(inp,ignore_errors=True); inp.mkdir(parents=True,exist_ok=True); zp=pdir/'architecture.zip'
    with zp.open('wb') as f: shutil.copyfileobj(file.file,f)
    try:
        safe_extract(zp,inp); fs=sorted(inp.rglob('*.dxf')); analysis={'file_count':len(fs),'files':[analyze_dxf(x) for x in fs]}
        if not fs: raise ValueError('DXF پیدا نشد')
        p.analysis=analysis; p.status='asking'; p.current_question=0; p.answers={}; p.last_error=''; db.commit()
    except Exception as e: p.last_error=str(e); db.commit()
    db.close(); return RedirectResponse(f'/projects/{pid}',303)

@app.post('/projects/{pid}/answer')
def answer(pid:int,request:Request,answer:str=Form(...)):
    u=current_user(request); db,p=own_project(pid,u.id if u else -1)
    if not p: raise HTTPException(404)
    qs=p.questions or []; idx=p.current_question
    if idx<len(qs):
        a=dict(p.answers or {}); a[qs[idx]['key']]=answer; p.answers=a; p.current_question=idx+1; p.status='ready_to_design' if p.current_question>=len(qs) else 'asking'; db.commit()
    db.close(); return RedirectResponse(f'/projects/{pid}',303)

@app.post('/projects/{pid}/design')
def design(pid:int,request:Request):
    u=current_user(request); db,p=own_project(pid,u.id if u else -1)
    if not p: raise HTTPException(404)
    revno=(p.current_revision or 0)+1; r=Revision(project_id=p.id,revision_no=revno,status='queued'); db.add(r); p.status='queued'; db.commit(); db.refresh(r); rid=r.id; db.close(); threading.Thread(target=run_design,args=(pid,rid),daemon=True).start(); return RedirectResponse(f'/projects/{pid}',303)

@app.post('/projects/{pid}/feedback')
def feedback(pid:int,request:Request,feedback:str=Form(...)):
    u=current_user(request); db,p=own_project(pid,u.id if u else -1)
    if not p: raise HTTPException(404)
    if any(x in feedback for x in ['همه پروژه','همیشه','باید در تمام','رول بوک','Rulebook']): db.add(RuleCandidate(project_id=p.id,feedback=feedback,candidate_rule=feedback))
    revno=(p.current_revision or 0)+1; r=Revision(project_id=p.id,revision_no=revno,status='queued',feedback=feedback); db.add(r); p.status='queued'; db.commit(); db.refresh(r); rid=r.id; db.close(); threading.Thread(target=run_design,args=(pid,rid),daemon=True).start(); return RedirectResponse(f'/projects/{pid}',303)

@app.get('/projects/{pid}/pdf/{rev}')
def get_pdf(pid:int,rev:int,request:Request):
    u=current_user(request); db,p=own_project(pid,u.id if u else -1)
    if not p: raise HTTPException(404)
    r=db.query(Revision).filter(Revision.project_id==p.id,Revision.revision_no==rev).first(); db.close()
    if not r or r.status!='ready' or not r.pdf_path: raise HTTPException(404)
    return FileResponse(r.pdf_path,media_type='application/pdf',filename=f'MEP_Project_{pid}_R{rev}.pdf')
