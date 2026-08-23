(() => {
  const page = document.querySelector('.discipline-page.mechanical');
  if (!page) return;
  const hero = page.querySelector('.discipline-hero');
  if (!hero) return;
  hero.classList.add('mechanical-landing-hero');
  hero.innerHTML = `
    <div class="container-wide mechanical-hero-v3-grid">
      <div class="mechanical-hero-v3-art">
        <img src="/static/hero-mechanical.svg?v=20260823-1049" width="1600" height="900" alt="نمای مهندسی سیستم‌های مکانیکی ساختمان شامل HVAC، آب، فاضلاب، ونت و گاز" decoding="sync" fetchpriority="high">
      </div>
      <div class="mechanical-hero-v3-copy">
        <div class="mechanical-hero-v3-eyebrow">همراه مکانیک</div>
        <h1>طراحی هوشمند<br>سیستم‌های مکانیکی ساختمان</h1>
        <p class="mechanical-hero-v3-lead">از تحلیل پلان معماری تا تولید نقشه‌ها، دیتیل‌ها و محاسبات با دقت، سرعت و استاندارد مهندسی.</p>
        <div class="mechanical-hero-v3-features" aria-label="مزیت‌های همراه مکانیک">
          <div class="mechanical-hero-v3-feature">تحلیل خودکار پلان معماری</div><div class="mechanical-hero-v3-feature">درخواست هوشمند اطلاعات موردنیاز</div><div class="mechanical-hero-v3-feature">تولید نقشه‌های تخصصی</div><div class="mechanical-hero-v3-feature">محاسبات قابل استنتاج</div>
        </div>
        <div class="mechanical-hero-v3-actions"><a class="mechanical-hero-v3-primary" href="#start">شروع پروژه جدید <span aria-hidden="true">←</span></a><a class="mechanical-hero-v3-secondary" href="#real-samples">مشاهده نمونه پروژه</a></div>
      </div>
      <div class="mechanical-hero-v3-meta" aria-label="مشخصات همراه مکانیک"><div><b>فرمت ورودی</b><span>DXF / ZIP</span></div><div><b>خروجی‌ها</b><span>نقشه، دیتیل، محاسبات</span></div><div><b>تحلیل سریع</b><span>Architecture-first</span></div><div><b>کنترل مهندسی</b><span>خروجی قابل بررسی</span></div></div>
    </div>`;
})();
