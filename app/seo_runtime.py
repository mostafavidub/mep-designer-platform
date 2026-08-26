from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

MECHANICAL_ARTICLE = {
    'slug': 'mechanical-building-plan',
    'title': 'نقشه تأسیسات مکانیکی ساختمان؛ از آب و فاضلاب تا HVAC',
    'excerpt': 'راهنمای کاربردی طراحی آب سرد و گرم، فاضلاب و ونت، گاز، گرمایش و سرمایش، تهویه، رایزر، دیتیل و کنترل هماهنگی با معماری.',
    'tag': 'مکانیک',
    'body': [],
}


def register_seo_articles(app, legacy):
    """Register SEO-only blog additions without changing engineering workflow code."""
    if getattr(app.state, 'seo_articles_registered', False):
        return

    if not any(post.get('slug') == MECHANICAL_ARTICLE['slug'] for post in legacy.BLOG):
        legacy.BLOG.insert(0, MECHANICAL_ARTICLE.copy())

    # Replace only the generic blog detail route so existing blog behavior stays intact
    # while dedicated SEO templates can be selected by slug.
    for route in list(app.router.routes):
        if getattr(route, 'path', None) == '/blog/{slug}' and 'GET' in (getattr(route, 'methods', None) or set()):
            app.router.routes.remove(route)

    @app.get('/blog/{slug}', response_class=HTMLResponse)
    def seo_article(slug: str, request: Request):
        post = next((item for item in legacy.BLOG if item.get('slug') == slug), None)
        if not post:
            raise HTTPException(404)
        if slug == 'electrical-building-plan':
            return legacy.templates.TemplateResponse('electrical_building_plan.html', {'request': request, 'post': post})
        if slug == 'mechanical-building-plan':
            return legacy.templates.TemplateResponse('mechanical_building_plan.html', {'request': request, 'post': post})
        return legacy.templates.TemplateResponse('article.html', {'request': request, 'post': post})

    app.state.seo_articles_registered = True
