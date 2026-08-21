(()=>{
  const body=document.body,header=document.querySelector('.site-header');
  const progress=document.querySelector('.scroll-progress span');
  const menu=document.querySelector('.nav-menu'),nav=document.querySelector('.top-nav');
  const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const onScroll=()=>{
    const y=scrollY,range=Math.max(1,document.documentElement.scrollHeight-innerHeight);
    header?.classList.toggle('is-scrolled',y>30);
    if(progress) progress.style.transform=`scaleX(${Math.min(1,y/range)})`;
  };
  addEventListener('scroll',onScroll,{passive:true});onScroll();
  menu?.addEventListener('click',()=>{const open=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(open));nav?.classList.toggle('is-open',open);body.classList.toggle('modal-open',open)});
  nav?.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{menu?.setAttribute('aria-expanded','false');nav.classList.remove('is-open');body.classList.remove('modal-open')}));

  const hero=document.querySelector('.home-hero'),title=hero?.querySelector('h1');
  if(hero&&!reduce){
    hero.addEventListener('pointermove',e=>{const r=hero.getBoundingClientRect();hero.style.setProperty('--pointer-x',`${(e.clientX-r.left-r.width/2)*.035}px`);hero.style.setProperty('--pointer-y',`${(e.clientY-r.top-r.height/2)*.035}px`)});
    const phrases=['طراحی هوشمند، فراتر از ترسیم','از پلان معماری تا تصمیم مهندسی','چیزی را حدس نمی‌زنیم؛ تحلیل می‌کنیم','تأسیسات دقیق‌تر، مسیر کوتاه‌تر'];let i=0;
    if(title) setInterval(()=>{title.classList.remove('kinetic-in');title.classList.add('kinetic-out');setTimeout(()=>{i=(i+1)%phrases.length;title.textContent=phrases[i];title.classList.remove('kinetic-out');title.classList.add('kinetic-in')},520)},3900);
  }

  const sections=[...document.querySelectorAll('main>section:not(.hero):not(.discipline-hero)')];
  if(!reduce&&'IntersectionObserver'in window){body.classList.add('motion-ready');const observer=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('is-revealed');observer.unobserve(e.target)}}),{threshold:.08,rootMargin:'0px 0px -8%'});sections.forEach(s=>observer.observe(s));}else sections.forEach(s=>s.classList.add('is-revealed'));

  document.querySelectorAll('.faq-list details').forEach(item=>item.addEventListener('toggle',()=>{if(item.open)item.parentElement.querySelectorAll('details[open]').forEach(other=>{if(other!==item)other.open=false})}));
})();
