(()=>{
  const doc=document.documentElement,body=document.body;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const header=document.querySelector('.site-header');
  const progress=document.querySelector('.scroll-progress span');
  const menu=document.querySelector('.nav-menu');
  const nav=document.querySelector('.top-nav');

  // One passive scroll listener for header state + progress. rAF prevents
  // layout work from running more often than the browser can paint.
  let ticking=false;
  const paintScroll=()=>{
    const y=scrollY;
    header?.classList.toggle('is-scrolled',y>30);
    if(progress){
      const range=Math.max(1,doc.scrollHeight-innerHeight);
      progress.style.transform=`scaleX(${Math.min(1,y/range)})`;
    }
    ticking=false;
  };
  addEventListener('scroll',()=>{if(!ticking){ticking=true;requestAnimationFrame(paintScroll)}},{passive:true});
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
