(()=>{
  const workflow=document.querySelector('[data-workflow-road]');
  const grid=document.querySelector('.service-cta-grid');
  if(!workflow||!grid)return;
  const section=grid.closest('section');
  if(!section)return;

  section.classList.add('service-stack-section');
  workflow.insertAdjacentElement('afterend',section);

  const head=section.querySelector('.section-head');
  if(head){
    head.className='service-stack-intro';
    head.innerHTML='<div class="service-stack-intro-inner"><div class="service-stack-eyebrow">OUR SERVICES</div><h2 class="service-stack-title">خدماتی که ما به مهندسان ارائه می‌کنیم</h2><p class="service-stack-subtitle">سه مسیر تخصصی در یک فضای کاری واحد؛ هر سرویس با منطق، ورودی‌ها و خروجی مستقل.</p></div>';
  }

  const cards=[...grid.querySelectorAll('.service-cta')];
  cards.forEach((card,i)=>card.style.setProperty('--stack-index',String(i)));
  const spacer=document.createElement('div');
  spacer.className='service-stack-end-spacer';
  grid.after(spacer);

  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(reduced)return;

  let ticking=false;
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const paint=()=>{
    const vh=innerHeight||document.documentElement.clientHeight;
    cards.forEach((card,i)=>{
      const next=cards[i+1];
      if(!next){
        card.style.setProperty('--stack-scale','1');
        card.style.setProperty('--stack-opacity','1');
        card.style.setProperty('--stack-brightness','1');
        return;
      }
      const nr=next.getBoundingClientRect();
      const trigger=vh*.82;
      const finish=vh*.18;
      const p=clamp((trigger-nr.top)/(trigger-finish),0,1);
      const scale=1-p*.085;
      const opacity=1-p*.18;
      const brightness=1-p*.13;
      card.style.setProperty('--stack-scale',scale.toFixed(4));
      card.style.setProperty('--stack-opacity',opacity.toFixed(4));
      card.style.setProperty('--stack-brightness',brightness.toFixed(4));
    });
    ticking=false;
  };
  const requestPaint=()=>{if(!ticking){ticking=true;requestAnimationFrame(paint)}};
  addEventListener('scroll',requestPaint,{passive:true});
  addEventListener('resize',requestPaint,{passive:true});
  requestPaint();
})();
