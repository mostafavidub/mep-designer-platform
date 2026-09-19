import json
from pathlib import Path

ARTICLES_PATH = Path(__file__).resolve().parent / "static" / "content" / "articles.json"

PUBLISHABLE_STATUSES = {"ready", "published"}


def load_generated_articles():
    try:
        raw = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

    if not isinstance(raw, list):
        return []

    posts = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        status = str(item.get("status") or "").strip().lower()
        if status not in PUBLISHABLE_STATUSES:
            continue

        slug = str(item.get("slug") or "").strip().strip("/")
        title = str(item.get("title") or "").strip()

        if not slug or not title:
            continue

        if "/" in slug or ".." in slug:
            continue

        meta_description = str(
            item.get("meta_description")
            or item.get("angle")
            or ""
        ).strip()

        page_type = str(item.get("page_type") or "").strip()

        posts.append({
            "slug": slug,
            "title": title,
            "excerpt": meta_description,
            "tag": page_type or "مقاله",
            "body": [],
            "generated": True,
            "html": str(item.get("html") or ""),
            "markdown": str(item.get("markdown") or ""),
            "primary_keyword": str(item.get("primary_keyword") or item.get("keyword") or ""),
            "secondary_keywords": item.get("secondary_keywords") or "",
            "created_date": str(item.get("created_date") or ""),
            "machine_score": item.get("machine_score"),
            "business_case": str(item.get("business_case") or ""),
            "engine_version": str(item.get("engine_version") or ""),
            "run_id": str(item.get("run_id") or ""),
        })

    return posts
