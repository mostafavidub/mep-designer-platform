(()=> {
  const carousels = [...document.querySelectorAll('[data-sample-carousel]')];
  carousels.forEach((carousel) => {
    const cards = [...carousel.querySelectorAll('.sample-card')];
    const counter = carousel.querySelector('[data-counter]');
    const lightbox = carousel.querySelector('.sample-lightbox');
    const largeImage = lightbox && lightbox.querySelector('.lightbox-content img');
    const caption = lightbox && lightbox.querySelector('[data-lightbox-caption]');
    let index = Math.max(0, cards.findIndex((card) => card.classList.contains('is-active')));

    const show = (nextIndex) => {
      if (!cards.length) return;
      index = (nextIndex + cards.length) % cards.length;
      cards.forEach((card, cardIndex) => {
        const active = cardIndex === index;
        card.classList.toggle('is-active', active);
        card.setAttribute('aria-hidden', String(!active));
      });
      if (counter) counter.textContent = `${index + 1} / ${cards.length}`;
    };

    carousel.querySelector('[data-prev]')?.addEventListener('click', () => show(index - 1));
    carousel.querySelector('[data-next]')?.addEventListener('click', () => show(index + 1));

    const close = () => {
      if (!lightbox) return;
      lightbox.hidden = true;
      lightbox.setAttribute('aria-hidden', 'true');
      largeImage?.removeAttribute('src');
      document.body.classList.remove('modal-open');
    };

    cards.forEach((card) => {
      card.querySelector('.sample-open')?.addEventListener('click', () => {
        if (!lightbox || !largeImage) return;
        const image = card.querySelector('img');
        if (!image) return;
        largeImage.src = image.currentSrc || image.src;
        largeImage.alt = image.alt;
        if (caption) caption.textContent = card.querySelector('figcaption')?.innerText || '';
        lightbox.hidden = false;
        lightbox.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');
        lightbox.querySelector('[data-close]')?.focus();
      });
    });

    lightbox?.querySelector('[data-close]')?.addEventListener('click', close);
    lightbox?.addEventListener('click', (event) => {
      if (event.target === lightbox) close();
    });
    document.addEventListener('keydown', (event) => {
      if (lightbox && !lightbox.hidden) {
        if (event.key === 'Escape') close();
        return;
      }
      if (event.key === 'ArrowLeft') show(index - 1);
      if (event.key === 'ArrowRight') show(index + 1);
    });

    show(index);
  });
})();