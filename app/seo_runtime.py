from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

SEO_ARTICLES = [
    {
        'slug': 'sanitary-drainage-plan',
        'title': 'نقشه فاضلاب ساختمان؛ اصول طراحی، شیب، ونت و رایزر',
        'excerpt': 'راهنمای طراحی مسیر فاضلاب، شیب، ونت، رایزر، دریچه بازدید و کنترل هماهنگی با معماری پیش از اجرا.',
        'tag': 'مکانیک',
        'body': [],
    },
    {
        'slug': 'mechanical-building-plan',
        'title': 'نقشه تأسیسات مکانیکی ساختمان؛ از آب و فاضلاب تا HVAC',
        'excerpt': 'راهنمای کاربردی طراحی آب سرد و گرم، فاضلاب و ونت، گاز، گرمایش و سرمایش، تهویه، رایزر، دیتیل و کنترل هماهنگی با معماری.',
        'tag': 'مکانیک',
        'body': [],
    },
]

TEMPLATES = {
    'electrical-building-plan': 'electrical_building_plan.html',
    'mechanical-building-plan': 'mechanical_building_plan.html',
    'sanitary-drainage-plan': 'sanitary_drainage_plan.html',
}


def register_seo_articles(app, legacy):
    """Register SEO-only blog additions without changing engineering workflow code."""
    if getattr(app.state, 'seo_articles_registered', False):
        return

    existing = {post.get('slug') for post in legacy.BLOG}
    for article in reversed(SEO_ARTICLES):
        if article['slug'] not in existing:
            legacy.BLOG.insert(0, article.copy())

    for route in list(app.router.routes):
        if getattr(route, 'path', None) == '/blog/{slug}' and 'GET' in (getattr(route, 'methods', None) or set()):
            app.router.routes.remove(route)

    @app.get('/blog/{slug}', response_class=HTMLResponse)
    def seo_article(slug: str, request: Request):
        post = next((item for item in legacy.BLOG if item.get('slug') == slug), None)
        if not post:
            raise HTTPException(404)
        template = TEMPLATES.get(slug, 'article.html')
        return legacy.templates.TemplateResponse(template, {'request': request, 'post': post})

    app.state.seo_articles_registered = True
