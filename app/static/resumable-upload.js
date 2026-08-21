(()=>{
  const form=document.getElementById('uploadForm');
  if(!form)return;
  const input=document.getElementById('file'),wrap=document.getElementById('uploadProgressWrap'),bar=document.getElementById('uploadBar'),pct=document.getElementById('uploadPercent'),status=document.getElementById('uploadStatus'),btn=document.getElementById('uploadButton');
  const modal=document.getElementById('projectModal'),modalBody=document.getElementById('modalBody'),modalTitle=document.getElementById('projectModalTitle'),modalBar=document.getElementById('modalProgressBar'),close=document.getElementById('modalClose');
  const discipline=(form.action.split('/').filter(Boolean).pop()||'mechanical');
  const CHUNK=512*1024;
  let projectId=null,flowUrl=null,timer=null;

  const setProgress=(value,text)=>{const v=Math.max(0,Math.min(100,Math.round(value)));bar.style.width=v+'%';pct.textContent=v+'%';if(text)status.textContent=text};
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const openModal=()=>{if(!modal)return;modal.hidden=false;modal.setAttribute('aria-hidden','false');document.body.classList.add('modal-open')};
  const closeModal=()=>{if(!modal)return;modal.hidden=true;modal.setAttribute('aria-hidden','true');document.body.classList.remove('modal-open');if(timer)clearTimeout(timer)};
  if(close)close.onclick=closeModal;
  modal?.querySelector('.project-modal-backdrop')?.addEventListener('click',closeModal);

  const summary=d=>{const a=d.auto_summary||[];return a.length?`<div class="note-bar"><b>مواردی که خودکار به‌دست آمد:</b><ul>${a.map(x=>`<li>${x}</li>`).join('')}</ul></div>`:''};
  function render(d){
    if(!modalBody||!modalTitle||!modalBar)return;
    modalBar.style.width=(d.progress||0)+'%';
    if(['uploading','analyzing'].includes(d.status)){modalTitle.textContent='در حال تحلیل پلان معماری';modalBody.innerHTML='<div class="modal-processing"><div class="analysis-loader"></div><div><b>در حال استخراج اطلاعات</b><p>فضاها، شفت‌ها و داده‌های قابل محاسبه بررسی می‌شوند.</p></div></div>';timer=setTimeout(loadFlow,1200);return}
    if(d.status==='asking'&&d.question){modalTitle.textContent=`فقط ${d.question_count} ابهام باقی مانده`;modalBody.innerHTML=summary(d)+`<div class="modal-question"><div class="modal-question-number">${d.current_index+1}</div><h3>${d.question.question}</h3><p class="muted">این مورد با اطمینان کافی از پلان به‌دست نیامد.</p><form id="answerForm"><textarea id="answer" rows="4" required autofocus placeholder="پاسخ کوتاه و دقیق..."></textarea><button class="btn primary wide" type="submit">ثبت و ادامه</button></form></div>`;document.getElementById('answerForm').onsubmit=submitAnswer;return}
    if(d.status==='ready_to_design'){modalBar.style.width='100%';modalTitle.textContent='تحلیل کامل شد';modalBody.innerHTML=summary(d)+`<div class="modal-ready"><div class="modal-ready-icon">✓</div><h3>اطلاعات لازم تکمیل است</h3><p>داده‌های قابل استخراج تحلیل شده‌اند.</p><button id="designBtn" class="btn primary wide">شروع طراحی ${d.discipline==='electrical'?'برق':'مکانیک'}</button></div>`;document.getElementById('designBtn').onclick=startDesign;return}
    if(['queued','designing'].includes(d.status)){modalTitle.textContent='در حال طراحی';modalBody.innerHTML=summary(d)+'<div class="modal-processing"><div class="analysis-loader"></div><div><b>موتور طراحی در حال اجراست</b><p>جانمایی، Routing و محاسبات مقدماتی در حال تولید است.</p></div></div>';timer=setTimeout(loadFlow,1600);return}
    if(d.status==='ready'){modalBar.style.width='100%';modalTitle.textContent='خروجی آماده است';modalBody.innerHTML=summary(d)+`<div class="modal-ready"><div class="modal-ready-icon">✓</div><h3>طراحی آماده شد</h3>${d.pdf_url?`<a class="btn primary wide" href="${d.pdf_url}">دانلود PDF</a>`:''}</div>`;return}
    if(['failed','awaiting_upload'].includes(d.status)){modalTitle.textContent='فرآیند متوقف شد';modalBody.innerHTML=`<div class="modal-error"><b>پیام سیستم</b><p>${d.error||'امکان ادامه وجود ندارد.'}</p></div>`;return}
    timer=setTimeout(loadFlow,1500);
  }
  async function loadFlow(){if(!flowUrl)return;try{const r=await fetch(flowUrl,{cache:'no-store'});if(!r.ok)throw new Error('flow');render(await r.json())}catch(_){timer=setTimeout(loadFlow,2000)}}
  async function submitAnswer(e){e.preventDefault();const v=document.getElementById('answer').value.trim();if(!v)return;const fd=new FormData();fd.append('answer',v);const r=await fetch(`/projects/${projectId}/answer-json`,{method:'POST',body:fd});render(await r.json())}
  async function startDesign(){const b=document.getElementById('designBtn');b.disabled=true;b.textContent='در حال شروع...';const r=await fetch(`/projects/${projectId}/design-json`,{method:'POST'});render(await r.json());timer=setTimeout(loadFlow,1000)}

  async function sendChunk(url,blob,index,total,filename){
    let lastError;
    for(let attempt=0;attempt<4;attempt++){
      try{
        const qs=new URLSearchParams({index:String(index),total:String(total),filename});
        const r=await fetch(`${url}?${qs}`,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:blob,cache:'no-store'});
        if(!r.ok)throw new Error(`HTTP ${r.status}`);
        return await r.json();
      }catch(e){lastError=e;if(attempt<3){status.textContent=`اتصال ناپایدار؛ تلاش مجدد ${attempt+1}/3...`;await sleep(700*(attempt+1))}}
    }
    throw lastError||new Error('upload failed');
  }

  form.onsubmit=async e=>{
    e.preventDefault();
    const file=input.files&&input.files[0];if(!file)return;
    wrap.hidden=false;btn.disabled=true;btn.textContent='در حال آپلود...';setProgress(0,'آماده‌سازی آپلود امن...');
    try{
      const name=(form.querySelector('[name="name"]')?.value||'').trim();
      const init=await fetch(`/api/upload/init/${discipline}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name}),cache:'no-store'});
      if(!init.ok)throw new Error(`init ${init.status}`);
      const session=await init.json();projectId=session.project_id;flowUrl=session.flow_url;
      const total=Math.ceil(file.size/CHUNK);
      for(let i=0;i<total;i++){
        const start=i*CHUNK,end=Math.min(file.size,start+CHUNK);
        await sendChunk(session.chunk_url,file.slice(start,end),i,total,file.name);
        const done=end/file.size*100;
        setProgress(done,done<100?'در حال آپلود...':'فایل دریافت شد؛ شروع تحلیل...');
      }
      setProgress(100,'فایل کامل دریافت شد؛ در حال تحلیل...');
      btn.textContent='در حال تحلیل...';openModal();loadFlow();
    }catch(err){
      console.error('Resumable upload failed',err);
      status.textContent='آپلود کامل نشد؛ اتصال را بررسی و دوباره تلاش کنید.';
      btn.disabled=false;btn.textContent='تلاش مجدد آپلود';
    }
  };
})();
