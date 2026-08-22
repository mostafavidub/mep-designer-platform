(()=>{
  const section=document.querySelector('[data-workflow-road]');
  if(!section)return;

  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const mobileQuery=matchMedia('(max-width: 760px)');
  const stops=[...section.querySelectorAll('[data-workflow-stop]')];
  let active=null;
  let ticking=false;

  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));

  const getParts=()=>{
    const svg=section.querySelector(mobileQuery.matches?'.workflow-road-svg-mobile':'.workflow-road-svg-desktop');
    if(!svg)return null;
    const progress=svg.querySelector('.workflow-road-progress');
    const runner=svg.querySelector('.workflow-road-runner');
    const core=svg.querySelector('.workflow-road-runner-core');
    if(!progress||!runner||!core)return null;
    const length=progress.getTotalLength();
    progress.style.strokeDasharray=`${length}`;
    return {svg,progress,runner,core,length};
  };

  const setStepState=p=>{
    const thresholds=[.04,.31,.59,.86];
    stops.forEach((stop,index)=>{
      const t=thresholds[index];
      const next=thresholds[index+1]??1.01;
      stop.classList.toggle('is-active',p>=t&&p<next);
      stop.classList.toggle('is-passed',p>=next);
    });
  };

  const prepare=()=>{
    active=getParts();
    if(!active)return;
    if(reduced){
      active.progress.style.strokeDashoffset='0';
      const end=active.progress.getPointAtLength(active.length);
      active.runner.setAttribute('cx',end.x);active.runner.setAttribute('cy',end.y);
      active.core.setAttribute('cx',end.x);active.core.setAttribute('cy',end.y);
      stops.forEach(s=>s.classList.add('is-passed'));
      return;
    }
    paint();
  };

  const paint=()=>{
    if(!active||reduced){ticking=false;return}
    const rect=section.getBoundingClientRect();
    const vh=innerHeight||document.documentElement.clientHeight;
    const start=vh*.72;
    const end=Math.max(1,rect.height-vh*.42);
    const p=clamp((start-rect.top)/end,0,1);
    const offset=active.length*(1-p);
    active.progress.style.strokeDashoffset=`${offset}`;
    const point=active.progress.getPointAtLength(active.length*p);
    active.runner.setAttribute('cx',point.x);active.runner.setAttribute('cy',point.y);
    active.core.setAttribute('cx',point.x);active.core.setAttribute('cy',point.y);
    setStepState(p);
    ticking=false;
  };

  const requestPaint=()=>{
    if(!ticking){ticking=true;requestAnimationFrame(paint)}
  };

  addEventListener('scroll',requestPaint,{passive:true});
  addEventListener('resize',()=>{active=getParts();requestPaint()},{passive:true});
  mobileQuery.addEventListener?.('change',()=>{active=getParts();requestPaint()});
  prepare();
})();
