"""Read-only Google Search Console reporting endpoints.

Credentials and the endpoint key are read exclusively from environment
variables. Nothing from this module persists credentials to disk or logs them.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from datetime import date, timedelta
from typing import Any, Optional
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
from fastapi import APIRouter, Header, HTTPException, Query, Request
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account


SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
SEARCH_ANALYTICS_URL = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
URL_INSPECTION_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _service_account_info() -> dict[str, Any]:
    raw = _required_env("GSC_SERVICE_ACCOUNT_JSON")
    try:
        if not raw.lstrip().startswith("{"):
            raw = base64.b64decode(raw, validate=True).decode("utf-8")
        info = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("GSC_SERVICE_ACCOUNT_JSON is not valid JSON or base64 JSON") from exc
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise RuntimeError("GSC_SERVICE_ACCOUNT_JSON must contain a service account key")
    return info


def _authorized_session() -> AuthorizedSession:
    credentials = service_account.Credentials.from_service_account_info(
        _service_account_info(), scopes=[SEARCH_CONSOLE_SCOPE]
    )
    return AuthorizedSession(credentials)


def _check_internal_key(authorization: Optional[str], x_seo_report_key: Optional[str]) -> None:
    expected = _required_env("SEO_REPORT_API_KEY")
    supplied = x_seo_report_key or ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _fetch_sitemap_urls(sitemap_url: str) -> list[str]:
    response = requests.get(sitemap_url, timeout=20, headers={"User-Agent": "EngiTools-SEO-Reporter/1.0"})
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    if root.tag == f"{namespace}sitemapindex":
        urls: list[str] = []
        for loc in root.findall(f"{namespace}sitemap/{namespace}loc"):
            if loc.text:
                urls.extend(_fetch_sitemap_urls(loc.text.strip()))
        return sorted(set(urls))
    return sorted({loc.text.strip() for loc in root.findall(f"{namespace}url/{namespace}loc") if loc.text})


def _search_analytics(session: AuthorizedSession, site_url: str, start_date: str, end_date: str, row_limit: int) -> list[dict[str, Any]]:
    response = session.post(
        SEARCH_ANALYTICS_URL.format(site=requests.utils.quote(site_url, safe="")),
        json={
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["query", "page"],
            "rowLimit": row_limit,
            "dataState": "final",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("rows", [])


def _inspect(session: AuthorizedSession, site_url: str, urls: list[str]) -> list[dict[str, Any]]:
    results = []
    for inspected_url in urls:
        try:
            response = session.post(
                URL_INSPECTION_URL,
                json={"inspectionUrl": inspected_url, "siteUrl": site_url, "languageCode": "fa-IR"},
                timeout=30,
            )
            response.raise_for_status()
            result = response.json().get("inspectionResult", {})
            index = result.get("indexStatusResult", {})
            results.append({
                "url": inspected_url,
                "verdict": index.get("verdict"),
                "coverageState": index.get("coverageState"),
                "indexingState": index.get("indexingState"),
                "robotsTxtState": index.get("robotsTxtState"),
                "pageFetchState": index.get("pageFetchState"),
                "lastCrawlTime": index.get("lastCrawlTime"),
                "googleCanonical": index.get("googleCanonical"),
                "userCanonical": index.get("userCanonical"),
            })
        except requests.RequestException as exc:
            results.append({"url": inspected_url, "error": str(exc)})
    return results


def register_gsc_routes(app) -> None:
    if getattr(app.state, "gsc_routes_registered", False):
        return
    router = APIRouter(prefix="/internal/seo", tags=["internal"], include_in_schema=False)

    @router.get("/report")
    def seo_report(
        request: Request,
        days: int = Query(28, ge=1, le=90),
        row_limit: int = Query(1000, ge=1, le=25000),
        inspect_limit: int = Query(25, ge=0, le=100),
        authorization: Optional[str] = Header(None),
        x_seo_report_key: Optional[str] = Header(None),
    ):
        try:
            _check_internal_key(authorization, x_seo_report_key)
            site_url = _required_env("GSC_SITE_URL")
            public_base = os.getenv("PUBLIC_SITE_URL", "").strip().rstrip("/") or str(request.base_url).rstrip("/")
            sitemap_url = os.getenv("GSC_SITEMAP_URL", "").strip() or urljoin(public_base + "/", "sitemap.xml")
            end = date.today() - timedelta(days=3)
            start = end - timedelta(days=days - 1)
            session = _authorized_session()
            rows = _search_analytics(session, site_url, start.isoformat(), end.isoformat(), row_limit)
            sitemap_urls = _fetch_sitemap_urls(sitemap_url)
            performance_urls = sorted({row.get("keys", [None, None])[1] for row in rows if len(row.get("keys", [])) > 1})
            missing_performance = sorted(set(sitemap_urls) - set(performance_urls))
            inspection_targets = missing_performance[:inspect_limit]
            inspections = _inspect(session, site_url, inspection_targets) if inspection_targets else []
            totals = {
                "clicks": sum(float(row.get("clicks", 0)) for row in rows),
                "impressions": sum(float(row.get("impressions", 0)) for row in rows),
            }
            totals["ctr"] = totals["clicks"] / totals["impressions"] if totals["impressions"] else 0
            return {
                "period": {"startDate": start.isoformat(), "endDate": end.isoformat()},
                "siteUrl": site_url,
                "totals": totals,
                "searchAnalytics": rows,
                "sitemap": {
                    "url": sitemap_url,
                    "urlCount": len(sitemap_urls),
                    "urls": sitemap_urls,
                    "urlsWithoutPerformanceRows": missing_performance,
                },
                "urlInspection": {"requested": len(inspection_targets), "results": inspections},
            }
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (requests.RequestException, ElementTree.ParseError) as exc:
            raise HTTPException(status_code=502, detail=f"Upstream SEO service error: {exc}") from exc

    app.include_router(router)
    app.state.gsc_routes_registered = True
