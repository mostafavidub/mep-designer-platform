(()=>{
  const hero=document.querySelector('.home-hero');
  if(!hero)return;

  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const next=hero.nextElementSibling;
  if(!next)return;

  // One scene owns both layers. Keeping the overlay inside the same containing
  // block is what lets the hero stay pinned until the next section has fully
  // travelled over it instead of scrolling away after the initial overlap.
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
    // Hero transformation completes before the second layer starts covering it.
    // After this short opening phase the values clamp and the hero visually
    // freezes in place while the content layer continues upwards.
    const shrinkDistance=Math.max(180,innerHeight*.28);
    const p=clamp((-rect.top)/shrinkDistance,0,1);
    const eased=1-Math.pow(1-p,2.35);

    const scale=1-(eased*.10);
    const radius=eased*28;
    const brightness=1-(eased*.17);
    const opacity=1-(eased*.06);

    hero.style.transform=`translate3d(0,0,0) scale(${scale})`;
    hero.style.borderRadius=`${radius}px`;
    hero.style.filter=`brightness(${brightness})`;
    hero.style.opacity=String(opacity);

    if(grid){
      grid.style.transform=`translate3d(0,${-(eased*8)}px,0) scale(${1-(eased*.016)})`;
      grid.style.opacity=String(1-(eased*.12));
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
