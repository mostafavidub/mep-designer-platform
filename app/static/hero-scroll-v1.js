(()=>{
  const hero=document.querySelector('.home-hero');
  if(!hero)return;

  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  // The workflow is intentionally the layer that covers the hero. Do not use
  // nextElementSibling here: the services script reorders sections on home.
  const next=document.querySelector('[data-workflow-road]');
  if(!next)return;

  const scene=document.createElement('div');
  scene.className='hero-scroll-scene';
  hero.parentNode.insertBefore(scene,hero);
  scene.appendChild(hero);
  scene.appendChild(next);
  next.classList.add('hero-overlap-next');

  if(reduced)return;

  const grid=hero.querySelector('.hero-grid');
  let ticking=false;
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));

  const paint=()=>{
    const rect=scene.getBoundingClientRect();
    // Short opening zoom-out. Once complete, the hero stays visually frozen
    // while the workflow sheet keeps travelling over it.
    const shrinkDistance=Math.max(180,innerHeight*.24);
    const p=clamp((-rect.top)/shrinkDistance,0,1);
    const eased=1-Math.pow(1-p,2.35);

    const scale=1-(eased*.085);
    const radius=eased*26;
    const brightness=1-(eased*.16);
    const opacity=1-(eased*.05);

    hero.style.transform=`translate3d(0,0,0) scale(${scale})`;
    hero.style.borderRadius=`${radius}px`;
    hero.style.filter=`brightness(${brightness})`;
    hero.style.opacity=String(opacity);

    if(grid){
      grid.style.transform=`translate3d(0,${-(eased*7)}px,0) scale(${1-(eased*.014)})`;
      grid.style.opacity=String(1-(eased*.10));
    }
    ticking=false;
  };

  const requestPaint=()=>{
    if(!ticking){ticking=true;requestAnimationFrame(paint)}
  };

  addEventListener('scroll',requestPaint,{passive:true});
  addEventListener('resize',requestPaint,{passive:true});
  paint();
})();
