(()=>{
  const doc=document.documentElement,body=document.body;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const header=document.querySelector('.site-header');
  const progress=document.querySelector('.scroll-progress span');
  const menu=document.querySelector('.nav-menu');
  const nav=document.querySelector('.top-nav');

  // Home hero: layered, UNStudio-inspired transition. The hero becomes a
  // sticky visual plane that subtly zooms out while the next section rises
  // over it. This is deliberately implemented with transforms only so the
  // scroll interaction does not cause layout thrashing or CLS.
  let heroScene=null;
  const homeHero=document.querySelector('.home-hero');
  if(homeHero && location.pathname==='/' && !reduced){
    const shell=document.createElement('div');
    shell.className='hero-scroll-shell';
    homeHero.parentNode.insertBefore(shell,homeHero);
    shell.appendChild(homeHero);
    const next=shell.nextElementSibling;
    if(next) next.classList.add('hero-overlap-next');
    heroScene={shell,hero:homeHero,next};
  }

  const clamp=(n,min=0,max=1)=>Math.max(min,Math.min(max,n));
  const paintHero=()=>{
    if(!heroScene)return;
    const {shell,hero}=heroScene;
    const headerH=header?.offsetHeight||0;
    doc.style.setProperty('--site-header-h',`${headerH}px`);
    const rect=shell.getBoundingClientRect();
    const stickyH=Math.max(1,innerHeight-headerH);
    const travel=Math.max(1,shell.offsetHeight-stickyH);
    const p=clamp((headerH-rect.top)/travel);
    const mobile=innerWidth<=640;
    const scale=1-p*(mobile?.035:.075);
    const radius=p*(mobile?12:24);
    const y=p*(mobile?4:12);
    const dim=1-p*(mobile?.04:.09);
    hero.style.setProperty('--hero-scale',scale.toFixed(4));
    hero.style.setProperty('--hero-radius',`${radius.toFixed(2)}px`);
    hero.style.setProperty('--hero-y',`${y.toFixed(2)}px`);
    hero.style.setProperty('--hero-dim',dim.toFixed(4));
    shell.style.setProperty('--hero-progress',p.toFixed(4));
  };

  // One passive scroll listener for header state, page progress and the hero
  // scene. rAF keeps all scroll-linked painting in a single browser frame.
  let ticking=false;
  const paintScroll=()=>{
    const y=scrollY;
    header?.classList.toggle('is-scrolled',y>30);
    if(progress){
      const range=Math.max(1,doc.scrollHeight-innerHeight);
      progress.style.transform=`scaleX(${Math.min(1,y/range)})`;
    }
    paintHero();
    ticking=false;
  };
  addEventListener('scroll',()=>{if(!ticking){ticking=true;requestAnimationFrame(paintScroll)}},{passive:true});
  addEventListener('resize',()=>requestAnimationFrame(paintScroll),{passive:true});
  paintScroll();

  const setMenuOpen=open=>{
    menu?.setAttribute('aria-expanded',String(open));
    menu?.setAttribute('aria-label',open?'بستن منو':'باز کردن منو');
    nav?.classList.toggle('is-open',open);
    body.classList.toggle('modal-open',open);
  };
  menu?.addEventListener('click',()=>setMenuOpen(menu.getAttribute('aria-expanded')!=='true'));
  nav?.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>setMenuOpen(false)));
  addEventListener('keydown',e=>{if(e.key==='Escape'&&menu?.getAttribute('aria-expanded')==='true'){setMenuOpen(false);menu.focus()}});

  // Stable hero copy: no timer-driven H1 replacement, avoiding layout shift
  // and keeping the visible heading aligned with the document's SEO meaning.
  const targets=[...document.querySelectorAll('.section,.blog-card,.article-wrap h2,.article-featured,.article-visual-grid figure')];
  targets.forEach((el,i)=>{
    el.classList.add('reveal-brand');
    if(reduced) el.classList.add('is-visible');
    else el.style.transitionDelay=`${Math.min(i%4,3)*45}ms`;
  });
  if(!reduced&&'IntersectionObserver'in window){
    const io=new IntersectionObserver(entries=>{
      for(const e of entries){if(e.isIntersecting){e.target.classList.add('is-visible');io.unobserve(e.target)}}
    },{threshold:.08,rootMargin:'0px 0px -6% 0px'});
    targets.forEach(el=>io.observe(el));
  }else targets.forEach(el=>el.classList.add('is-visible'));

  const path=location.pathname;
  nav?.querySelectorAll('a').forEach(a=>{
    const href=a.getAttribute('href');
    if(href==='/'?path==='/':path.startsWith(href)) a.setAttribute('aria-current','page');
  });

  document.querySelectorAll('.faq-list details').forEach(item=>item.addEventListener('toggle',()=>{
    if(item.open)item.parentElement.querySelectorAll('details[open]').forEach(other=>{if(other!==item)other.open=false});
  }));

  document.querySelectorAll('.service-cta,.trust-grid article,.deliverable-grid article,.limit-grid article').forEach((el,i)=>{
    el.setAttribute('data-brand-code',`ET / ${String(i+1).padStart(2,'0')}`);
  });
})();
