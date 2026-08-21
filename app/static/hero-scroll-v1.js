(()=>{
  const hero=document.querySelector('.home-hero');
  if(!hero)return;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Build a dedicated scroll stage without changing semantic heading/content structure.
  const stage=document.createElement('div');
  stage.className='hero-scroll-stage';
  hero.parentNode.insertBefore(stage,hero);
  stage.appendChild(hero);
  const next=stage.nextElementSibling;
  if(next)next.classList.add('hero-overlap-next');
  if(reduced)return;

  const grid=hero.querySelector('.hero-grid');
  let ticking=false;
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const paint=()=>{
    const rect=stage.getBoundingClientRect();
    const scrollable=Math.max(1,stage.offsetHeight-innerHeight);
    const progressed=clamp((-rect.top)/scrollable,0,1);
    // Strongest change happens in the latter half, creating the 'receding sheet' feel.
    const eased=1-Math.pow(1-progressed,2.15);
    const scale=1-(eased*.105);
    const y=-(eased*18);
    const radius=eased*26;
    const brightness=1-(eased*.18);
    const opacity=1-(eased*.08);
    hero.style.transform=`translate3d(0,${y}px,0) scale(${scale})`;
    hero.style.borderRadius=`${radius}px ${radius}px 0 0`;
    hero.style.filter=`brightness(${brightness})`;
    hero.style.opacity=String(opacity);
    if(grid){
      grid.style.transform=`translate3d(0,${-(eased*12)}px,0) scale(${1-(eased*.018)})`;
      grid.style.opacity=String(1-(eased*.16));
    }
    ticking=false;
  };
  const requestPaint=()=>{if(!ticking){ticking=true;requestAnimationFrame(paint)}};
  addEventListener('scroll',requestPaint,{passive:true});
  addEventListener('resize',requestPaint,{passive:true});
  paint();
})();
