(()=>{
  const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.querySelectorAll('[data-sample-carousel]').forEach(carousel=>{
    const cards=[...carousel.querySelectorAll('.sample-card')],counter=carousel.querySelector('[data-counter]');
    const lightbox=carousel.querySelector('.sample-lightbox'),large=lightbox?.querySelector('.lightbox-content img'),caption=lightbox?.querySelector('[data-lightbox-caption]');
    if(large&&!large.getAttribute('alt'))large.alt='نمایش بزرگ نمونه نقشه پروژه EngiTools';
    let index=Math.max(0,cards.findIndex(c=>c.classList.contains('is-active'))),timer,startX=null,dragging=false;
    const progress=document.createElement('div');progress.className='carousel-progress';progress.innerHTML='<span></span>';carousel.append(progress);
    const paint=()=>{if(counter)counter.textContent=`${String(index+1).padStart(2,'0')} / ${String(cards.length).padStart(2,'0')}`;progress.querySelector('span').style.transform=`scaleX(${(index+1)/cards.length})`};
    const show=(next,direction=next>=index?'next':'prev')=>{
      if(!cards.length)return;const old=index;index=(next+cards.length)%cards.length;if(old===index){paint();return}
      carousel.dataset.direction=direction;const previous=cards[old];previous.classList.remove('is-active');previous.classList.add('is-leaving');previous.setAttribute('aria-hidden','true');
      cards[index].classList.add('is-active');cards[index].setAttribute('aria-hidden','false');cards.forEach((card,i)=>{if(i!==index&&i!==old)card.setAttribute('aria-hidden','true')});
      setTimeout(()=>previous.classList.remove('is-leaving'),980);paint();restart();
    };
    const next=()=>show(index+1,'next'),prev=()=>show(index-1,'prev');
    carousel.querySelector('[data-prev]')?.addEventListener('click',prev);carousel.querySelector('[data-next]')?.addEventListener('click',next);
    const restart=()=>{clearInterval(timer);if(!reduce&&!document.hidden)timer=setInterval(next,6500)};carousel.addEventListener('mouseenter',()=>clearInterval(timer));carousel.addEventListener('mouseleave',restart);carousel.addEventListener('focusin',()=>clearInterval(timer));carousel.addEventListener('focusout',restart);
    carousel.addEventListener('pointerdown',e=>{if(e.target.closest('.carousel-arrow'))return;startX=e.clientX;dragging=true;carousel.classList.add('is-dragging')});
    carousel.addEventListener('pointerup',e=>{if(!dragging)return;const delta=e.clientX-startX;dragging=false;carousel.classList.remove('is-dragging');if(Math.abs(delta)>55)(delta<0?next:prev)();startX=null});carousel.addEventListener('pointercancel',()=>{dragging=false;carousel.classList.remove('is-dragging')});
    const close=()=>{if(!lightbox)return;lightbox.hidden=true;lightbox.setAttribute('aria-hidden','true');large?.removeAttribute('src');document.body.classList.remove('modal-open');restart()};
    cards.forEach(card=>card.querySelector('.sample-open')?.addEventListener('click',()=>{if(!lightbox||!large)return;const img=card.querySelector('img');if(!img)return;clearInterval(timer);large.src=img.currentSrc||img.src;large.alt=img.alt||'نمایش بزرگ نمونه نقشه پروژه EngiTools';caption.textContent=card.querySelector('figcaption')?.innerText||'';lightbox.hidden=false;lightbox.setAttribute('aria-hidden','false');document.body.classList.add('modal-open');lightbox.querySelector('[data-close]')?.focus()}));
    lightbox?.querySelector('[data-close]')?.addEventListener('click',close);lightbox?.addEventListener('click',e=>{if(e.target===lightbox)close()});
    document.addEventListener('keydown',e=>{if(lightbox&&!lightbox.hidden){if(e.key==='Escape')close();return}if(e.key==='ArrowLeft')prev();if(e.key==='ArrowRight')next()});
    cards.forEach((card,i)=>card.setAttribute('aria-hidden',String(i!==index)));paint();restart();
  });
})();
