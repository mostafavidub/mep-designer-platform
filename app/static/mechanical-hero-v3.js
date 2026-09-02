(() => {
  const page = document.querySelector('.discipline-page.mechanical');
  if (!page) return;
  const hero = page.querySelector('.discipline-hero');
  if (!hero) return;
  const title = 'طراحی هوشمند<br>سیستم‌های مکانیکی ساختمان';
  const lead = 'از تحلیل پلان معماری تا تولید نقشه‌ها، دیتیل‌ها و محاسبات با دقت، سرعت و استاندارد مهندسی.';
  const features = ['تحلیل خودکار پلان معماری','درخواست هوشمند اطلاعات موردنیاز','تولید نقشه‌های تخصصی','محاسبات قابل استنتاج'];
  const image = 'https://res.cloudinary.com/pnuzoh4o/image/upload/v1787475602/engitools/mechanical-hero-20260823-final.webp';
  const alt = 'مدل سه‌بعدی سیستم‌های مکانیکی ساختمان شامل تجهیزات HVAC، کانال‌ها و لوله‌کشی روی نقشه مهندسی';
  hero.classList.add('mechanical-landing-hero');
  hero.innerHTML = `
    <div class="container-wide mechanical-hero-v3-grid">
      <div class="mechanical-hero-v3-art"><img src="${image}" width="1536" height="1024" alt="${alt}" decoding="async" fetchpriority="high"></div>
      <div class="mechanical-hero-v3-copy">
        <div class="mechanical-hero-v3-eyebrow">همراه مکانیک</div>
        <h1>${title}</h1>
        <p class="mechanical-hero-v3-lead">${lead}</p>
        <div class="mechanical-hero-v3-features" aria-label="مزیت‌های همراه مکانیک">${features.map(item=>`<div class="mechanical-hero-v3-feature">${item}</div>`).join('')}</div>
        <div class="mechanical-hero-v3-actions"><a class="mechanical-hero-v3-primary" href="#start">شروع پروژه جدید <span aria-hidden="true">←</span></a><a class="mechanical-hero-v3-secondary" href="#real-samples">مشاهده نمونه پروژه</a></div>
      </div>
      <div class="mechanical-hero-v3-meta" aria-label="مشخصات همراه مکانیک"><div><b>فرمت ورودی</b><span>DXF / ZIP</span></div><div><b>خروجی‌ها</b><span>نقشه، دیتیل، محاسبات</span></div><div><b>تحلیل سریع</b><span>Architecture-first</span></div><div><b>کنترل مهندسی</b><span>خروجی قابل بررسی</span></div></div>
    </div>`;
})();
