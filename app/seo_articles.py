import json
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


ARTICLES_PATH = (
    Path(__file__).resolve().parent
    / "templates"
    / "content"
    / "articles.json"
)

PUBLISHABLE_STATUSES = {"published"}

ALLOWED_TAGS = {
    "p",
    "h2",
    "h3",
    "h4",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "b",
    "i",
    "a",
    "blockquote",
    "code",
    "pre",
    "br",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "sup",
    "sub",
}

VOID_TAGS = {
    "br",
    "hr",
}

BLOCKED_TAGS = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "svg",
    "math",
}

ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
}


def _safe_href(value):
    value = str(value or "").strip()

    if not value:
        return None

    if value.startswith("#"):
        return value

    if value.startswith("/") and not value.startswith("//"):
        return value

    parsed = urlparse(value)

    if parsed.scheme.lower() in {"http", "https", "mailto"}:
        return value

    return None


class ArticleHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.blocked_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag in BLOCKED_TAGS:
            self.blocked_depth += 1
            return

        if self.blocked_depth:
            return

        if tag not in ALLOWED_TAGS:
            return

        safe_attrs = []

        for name, value in attrs:
            name = name.lower()

            if name not in ALLOWED_ATTRIBUTES.get(tag, set()):
                continue

            if tag == "a" and name == "href":
                value = _safe_href(value)

                if value is None:
                    continue

            if tag == "a" and name == "target":
                if value not in {"_blank", "_self"}:
                    continue

            if name in {"colspan", "rowspan"}:
                if not str(value or "").isdigit():
                    continue

            safe_attrs.append(
                f'{name}="{escape(str(value), quote=True)}"'
            )

        if tag == "a":
            target_blank = any(
                name == "target" and value == "_blank"
                for name, value in attrs
            )

            if target_blank:
                safe_attrs.append('rel="noopener noreferrer"')

        attrs_text = ""

        if safe_attrs:
            attrs_text = " " + " ".join(safe_attrs)

        self.parts.append(f"<{tag}{attrs_text}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()

        if tag in BLOCKED_TAGS or self.blocked_depth:
            return

        if tag not in VOID_TAGS:
            return

        self.parts.append(f"<{tag}>")

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in BLOCKED_TAGS:
            if self.blocked_depth:
                self.blocked_depth -= 1
            return

        if self.blocked_depth:
            return

        if tag not in ALLOWED_TAGS:
            return

        if tag in VOID_TAGS:
            return

        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self.blocked_depth:
            return

        self.parts.append(escape(data))


def sanitize_article_html(raw_html):
    sanitizer = ArticleHTMLSanitizer()
    sanitizer.feed(str(raw_html or ""))
    sanitizer.close()
    return "".join(sanitizer.parts)


def load_generated_articles():
    try:
        raw = json.loads(
            ARTICLES_PATH.read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

    if not isinstance(raw, list):
        return []

    posts = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        status = str(
            item.get("status") or ""
        ).strip().lower()

        if status not in PUBLISHABLE_STATUSES:
            continue

        slug = str(
            item.get("slug") or ""
        ).strip().strip("/")

        title = str(
            item.get("title") or ""
        ).strip()

        if not slug or not title:
            continue

        if "/" in slug or ".." in slug:
            continue

        meta_description = str(
            item.get("meta_description")
            or item.get("angle")
            or ""
        ).strip()

        page_type = str(
            item.get("page_type") or ""
        ).strip()

        posts.append(
            {
                "slug": slug,
                "title": title,
                "excerpt": meta_description,
                "tag": page_type or "مقاله",
                "body": [],
                "generated": True,
                "html": sanitize_article_html(
                    item.get("html") or ""
                ),
                "markdown": str(
                    item.get("markdown") or ""
                ),
                "primary_keyword": str(
                    item.get("primary_keyword")
                    or item.get("keyword")
                    or ""
                ),
                "secondary_keywords": (
                    item.get("secondary_keywords") or ""
                ),
                "created_date": str(
                    item.get("created_date") or ""
                ),
                "machine_score": item.get(
                    "machine_score"
                ),
                "business_case": str(
                    item.get("business_case") or ""
                ),
                "engine_version": str(
                    item.get("engine_version") or ""
                ),
                "run_id": str(
                    item.get("run_id") or ""
                ),
            }
        )

    return posts
