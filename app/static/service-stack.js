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
  if(!head||!cards.length)return;

  const artSources=[
    '/service-art/mechanical.jpg?v=20260822-2015',
    '/static/service-art-electrical.svg?v=20260822-1535',
    '/static/service-art-architect.svg?v=20260822-1405'
  ];

  cards.forEach((card,i)=>{
    card.classList.add(`service-card-${i+1}`);
    if(i===1)card.classList.add('service-card-dark');
    if(i===2){
      card.classList.add('service-card-muted');
      const copy=card.querySelector('.cta-body p');
      if(copy)copy.textContent='نقشه زمین و مشخصات پروژه را می‌گیرد و مجموعه پلان‌های معماری را طراحی می‌کند.';
    }

    if(!card.querySelector('.service-stack-art')){
      const art=document.createElement('img');
      art.className='service-stack-art';
      art.src=artSources[i]||artSources[0];
      art.alt='';
      art.setAttribute('aria-hidden','true');
      art.decoding='async';
      art.loading=i===0?'eager':'lazy';
      card.prepend(art);
    }

    if(card.matches('a[href]')){
      card.classList.add('service-card-clickable');
      card.dataset.serviceHref=card.getAttribute('href')||'';
    }

    card.style.zIndex=String(30+i);
  });

  const scene=document.createElement('div');
  scene.className='service-stack-scene';
  const viewport=document.createElement('div');
  viewport.className='service-stack-viewport';
  const stage=document.createElement('div');
  stage.className='service-stack-stage';

  section.insertBefore(scene,head);
  scene.appendChild(viewport);
  viewport.appendChild(stage);
  stage.appendChild(head);
  stage.appendChild(grid);

  const layers=[head,...cards];
  scene.style.setProperty('--service-layer-count',String(layers.length));
  layers.forEach((layer,i)=>{
    layer.style.setProperty('--stack-index',String(i));
    layer.style.setProperty('--stack-enter',i===0?'0%':'108%');
    layer.style.setProperty('--stack-scale','1');
  });

  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(reduced)return;

  let ticking=false;
  let vh=innerHeight||document.documentElement.clientHeight;
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const ease=t=>1-Math.pow(1-t,3);

  const paint=()=>{
    const rect=scene.getBoundingClientRect();
    const travel=Math.max(1,scene.offsetHeight-vh);
    const overall=clamp((-rect.top)/travel,0,1);
    const transitions=layers.length-1;
    const segment=overall*transitions;

    layers.forEach((layer,i)=>{
      const enter=i===0?1:clamp(segment-(i-1),0,1);
      const cover=i<layers.length-1?clamp(segment-i,0,1):0;
      const enterY=(1-ease(enter))*108;
      const scale=1-(ease(cover)*0.065);
      layer.style.setProperty('--stack-enter',`${enterY.toFixed(3)}%`);
      layer.style.setProperty('--stack-scale',scale.toFixed(4));
    });
    ticking=false;
  };

  const requestPaint=()=>{if(!ticking){ticking=true;requestAnimationFrame(paint)}};
  addEventListener('scroll',requestPaint,{passive:true});
  addEventListener('resize',()=>{vh=innerHeight||document.documentElement.clientHeight;requestPaint()},{passive:true});
  requestPaint();
})();
