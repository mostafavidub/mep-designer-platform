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
  if(!cards.length)return;

  cards.forEach((card,i)=>{
    card.style.setProperty('--stack-index',String(i));
    card.style.setProperty('--stack-enter',i===0?'0%':'110%');
  });

  const scene=document.createElement('div');
  scene.className='service-stack-scene';
  scene.style.setProperty('--service-count',String(cards.length));
  const viewport=document.createElement('div');
  viewport.className='service-stack-viewport';
  grid.parentNode.insertBefore(scene,grid);
  scene.appendChild(viewport);
  viewport.appendChild(grid);

  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(reduced)return;

  let ticking=false;
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));

  const paint=()=>{
    const vh=innerHeight||document.documentElement.clientHeight;
    const rect=scene.getBoundingClientRect();
    const travel=Math.max(1,scene.offsetHeight-vh);
    const overall=clamp((-rect.top)/travel,0,1);
    const segment=overall*Math.max(1,cards.length-1);

    cards.forEach((card,i)=>{
      const enter=i===0?1:clamp(segment-(i-1),0,1);
      const cover=i<cards.length-1?clamp(segment-i,0,1):0;
      const enterY=(1-enter)*110;
      const scale=1-cover*.075;
      const opacity=1-cover*.16;
      const brightness=1-cover*.12;

      card.style.setProperty('--stack-enter',`${enterY.toFixed(3)}%`);
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
