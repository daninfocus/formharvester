"""Dependency-free, evidence-based website technology detection.

The detector consumes a small snapshot of browser-visible page signals.  This
keeps the matching rules testable without Selenium and makes it possible to
add a hosted provider later without changing the public harvest result.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

__all__ = [
    "PageSignals",
    "TechnologyDetector",
    "TechnologyEvidence",
    "TechnologyMatch",
]


@dataclass(frozen=True, slots=True)
class TechnologyEvidence:
    """A signal that supports a technology match."""

    source: str
    value: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "value": self.value, "detail": self.detail}


@dataclass(slots=True)
class TechnologyMatch:
    """A detected technology and the evidence behind it."""

    name: str
    category: str
    version: str | None = None
    confidence: float = 0.0
    evidence: list[TechnologyEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "version": self.version,
            "confidence": round(self.confidence, 3),
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(slots=True)
class PageSignals:
    """Browser-visible signals collected from one loaded page."""

    url: str = ""
    html: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    scripts: list[str] = field(default_factory=list)
    stylesheets: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    cookies: list[str] = field(default_factory=list)
    meta: dict[str, list[str]] = field(default_factory=dict)
    js_globals: set[str] = field(default_factory=set)


def _normalise_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in (headers or {}).items()}


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


class TechnologyDetector:
    """Match known technology fingerprints against :class:`PageSignals`."""

    @staticmethod
    def from_driver(driver: Any) -> PageSignals:
        """Capture signals from an existing Selenium-compatible driver.

        All browser access is defensive: a detector failure must never stop
        harvesting a site or submitting its form.
        """

        html = str(getattr(driver, "page_source", "") or "")
        url = str(getattr(driver, "current_url", "") or "")
        scripts: list[str] = []
        stylesheets: list[str] = []
        meta: dict[str, list[str]] = {}
        try:
            snapshot = driver.execute_script(
                """
                const metas = {};
                for (const node of document.querySelectorAll('meta[name], meta[property]')) {
                  const key = (node.getAttribute('name') || node.getAttribute('property') || '').toLowerCase();
                  if (!key) continue;
                  (metas[key] ||= []).push(node.getAttribute('content') || '');
                }
                return {
                  scripts: Array.from(document.scripts, node => node.src || ''),
                  stylesheets: Array.from(
                    document.querySelectorAll('link[rel~="stylesheet"]'), node => node.href || ''
                  ),
                  cookies: document.cookie ? document.cookie.split(';').map(value => value.trim()) : [],
                  meta: metas,
                  jsGlobals: [
                    '__NEXT_DATA__', '__NUXT__', '__REACT_DEVTOOLS_GLOBAL_HOOK__',
                    'Shopify', 'google_tag_manager', 'gtag', 'dataLayer',
                    'webpackJsonp', '___gatsby', 'webflow', 'Wix', 'squarespace'
                  ].filter(name => name in window),
                  resources: performance.getEntriesByType('resource').map(entry => entry.name)
                };
                """
            ) or {}
            scripts = [str(value) for value in snapshot.get("scripts", []) if value]
            stylesheets = [str(value) for value in snapshot.get("stylesheets", []) if value]
            meta = {
                str(key).lower(): [str(value) for value in values if value]
                for key, values in snapshot.get("meta", {}).items()
            }
            cookies = [str(value) for value in snapshot.get("cookies", []) if value]
            resources = [str(value) for value in snapshot.get("resources", []) if value]
            js_globals = {str(value) for value in snapshot.get("jsGlobals", []) if value}
        except Exception:
            cookies = []
            resources = []
            js_globals = set()

        if not cookies:
            try:
                cookies = [
                    f"{item.get('name', '')}={item.get('value', '')}"
                    for item in driver.get_cookies()
                    if item.get("name")
                ]
            except Exception:
                cookies = []

        headers: dict[str, str] = {}
        try:
            for entry in driver.get_log("performance"):
                message = json.loads(entry.get("message", "{}"))
                params = message.get("message", {}).get("params", {})
                if message.get("message", {}).get("method") != "Network.responseReceived":
                    continue
                response = params.get("response", {})
                response_url = str(response.get("url", ""))
                if response_url and url and urlparse(response_url).netloc != urlparse(url).netloc:
                    continue
                headers.update(_normalise_headers(response.get("headers")))
        except Exception:
            # Performance logging is optional and unavailable on some drivers.
            pass

        # The page source is also useful for extracting script/link URLs when a
        # driver stub does not implement execute_script.
        if html:
            soup = BeautifulSoup(html, "html.parser")
            scripts.extend(str(node.get("src", "")) for node in soup.find_all("script"))
            stylesheets.extend(
                str(node.get("href", ""))
                for node in soup.find_all("link", rel=lambda value: value and "stylesheet" in value)
            )
            for node in soup.find_all("meta"):
                key = str(node.get("name") or node.get("property") or "").lower()
                value = str(node.get("content") or "")
                if key and value:
                    meta.setdefault(key, []).append(value)

        return PageSignals(
            url=url,
            html=html,
            headers=headers,
            scripts=_unique(scripts),
            stylesheets=_unique(stylesheets),
            resources=_unique(resources),
            cookies=_unique(cookies),
            meta={key: _unique(values) for key, values in meta.items()},
            js_globals=js_globals,
        )

    def detect(self, signals: PageSignals) -> list[TechnologyMatch]:
        """Return deduplicated matches sorted by category and name."""

        html = signals.html.lower()
        all_urls = "\n".join(
            [signals.url, *signals.scripts, *signals.stylesheets, *signals.resources]
        ).lower()
        headers = _normalise_headers(signals.headers)
        header_text = "\n".join(f"{key}: {value}" for key, value in headers.items()).lower()
        cookie_names = {
            value.split("=", 1)[0].strip()
            for value in signals.cookies
            if value.split("=", 1)[0].strip()
        }
        meta_text = "\n".join(
            f"{key}: {' '.join(values)}" for key, values in signals.meta.items()
        ).lower()
        globals_lower = {value.lower() for value in signals.js_globals}
        matches: list[TechnologyMatch] = []

        def add(
            name: str,
            category: str,
            confidence: float,
            source: str,
            value: str,
            detail: str,
            version: str | None = None,
        ) -> None:
            matches.append(
                TechnologyMatch(
                    name=name,
                    category=category,
                    version=version,
                    confidence=confidence,
                    evidence=[TechnologyEvidence(source, value[:240], detail)],
                )
            )

        def url_match(
            needle: str,
            name: str,
            category: str,
            confidence: float,
            detail: str,
            version_pattern: str | None = None,
        ) -> None:
            match = re.search(needle, all_urls, re.IGNORECASE)
            if not match:
                return
            version = match.group(1) if version_pattern and match.lastindex else None
            add(name, category, confidence, "resource_url", match.group(0), detail, version)

        def text_match(
            needle: str,
            name: str,
            category: str,
            confidence: float,
            source: str,
            detail: str,
        ) -> None:
            match = re.search(needle, html, re.IGNORECASE)
            if match:
                add(name, category, confidence, source, match.group(0), detail)

        # CMS and hosted platforms.
        if re.search(r"(?:^|[\"'/])wp-(?:content|includes|json)(?:[\"'/])", html + all_urls):
            add("WordPress", "CMS", 0.98, "html_or_url", "wp-content/wp-includes/wp-json", "WordPress path")
        if "wordpress" in meta_text or re.search(
            r"<meta[^>]+(?:name|property)=[\"']generator[\"'][^>]+wordpress",
            html,
            re.IGNORECASE,
        ):
            add("WordPress", "CMS", 1.0, "meta", "generator=wordpress", "Generator meta tag")
        if re.search(r"cdn\.shopify\.com|shopify\.theme|shopify\.routes", html + all_urls, re.IGNORECASE):
            add("Shopify", "Ecommerce", 0.98, "html_or_url", "Shopify marker", "Shopify asset or global")
        if re.search(r"wixstatic\.com|wix-code|_wix_", html + all_urls, re.IGNORECASE):
            add("Wix", "Website builder", 0.95, "html_or_url", "Wix marker", "Wix asset or DOM marker")
        if re.search(r"squarespace\.com|squarespace", html + all_urls, re.IGNORECASE):
            add(
                "Squarespace",
                "Website builder",
                0.9,
                "html_or_url",
                "Squarespace marker",
                "Squarespace asset or marker",
            )
        if re.search(r"data-wf-site|webflow\.js|webflow\.com", html + all_urls, re.IGNORECASE):
            add("Webflow", "Website builder", 0.95, "html_or_url", "Webflow marker", "Webflow DOM or asset")

        # Frontend frameworks and asset libraries.
        if (
            "__next_data__" in globals_lower
            or re.search(r"id=[\"']__next_data__[\"']|/_next/(?:static|data)/", html + all_urls)
        ):
            add("Next.js", "Web framework", 0.98, "dom_or_url", "__NEXT_DATA__ or /_next/", "Next.js runtime marker")
        if "__nuxt__" in globals_lower or re.search(r"__nuxt__|/_nuxt/", html + all_urls):
            add("Nuxt", "Web framework", 0.98, "dom_or_url", "__NUXT__ or /_nuxt/", "Nuxt runtime marker")
        if re.search(r"astro-island|/_astro/", html + all_urls, re.IGNORECASE):
            add("Astro", "Web framework", 0.98, "html_or_url", "astro-island or /_astro/", "Astro runtime marker")
        if re.search(r"/_app/immutable/|__svelte", html + all_urls, re.IGNORECASE):
            add("SvelteKit", "Web framework", 0.96, "html_or_url", "SvelteKit marker", "SvelteKit runtime marker")
        if re.search(
            r"data-reactroot|react(?:-dom)?(?:\.production)?(?:\.min)?\.js|react\.development",
            html + all_urls,
            re.IGNORECASE,
        ):
            add("React", "JavaScript framework", 0.9, "html_or_url", "React marker", "React DOM or bundle marker")
        if re.search(
            r"ng-version|ng-app|@angular|angular(?:\.min)?\.js|zone\.js",
            html + all_urls,
            re.IGNORECASE,
        ):
            add(
                "Angular",
                "JavaScript framework",
                0.94,
                "html_or_url",
                "Angular marker",
                "Angular DOM or bundle marker",
            )
        if re.search(r"data-v-[0-9a-f]{5,}|vue(?:\.runtime)?(?:\.min)?\.js", html + all_urls, re.IGNORECASE):
            add("Vue.js", "JavaScript framework", 0.9, "html_or_url", "Vue marker", "Vue DOM or bundle marker")
        url_match(
            r"jquery(?:[-.]([0-9]+(?:\.[0-9]+)+))?(?:\.min)?\.js",
            "jQuery",
            "JavaScript library",
            0.95,
            "jQuery script",
            "jquery",
        )
        url_match(
            r"bootstrap(?:[-.]([0-9]+(?:\.[0-9]+)+))?(?:\.min)?\.(?:css|js)",
            "Bootstrap",
            "UI framework",
            0.95,
            "Bootstrap asset",
            "bootstrap",
        )
        if "tailwind" in all_urls or re.search(
            r"class=[\"'][^\"']*\b(?:flex|grid|space-[xy]|text-[a-z]+-[0-9]+)\b",
            html,
        ):
            add(
                "Tailwind CSS",
                "UI framework",
                0.7,
                "url_or_dom",
                "Tailwind marker",
                "Tailwind asset or utility classes",
            )

        # Marketing, analytics, payments and other browser services.
        if re.search(r"googletagmanager\.com|google_tag_manager", html + all_urls + header_text, re.IGNORECASE):
            add(
                "Google Tag Manager",
                "Analytics",
                0.98,
                "html_or_url",
                "GTM marker",
                "Google Tag Manager script or global",
            )
        if re.search(r"google-analytics\.com|gtag(?:\.js)?|googleanalytics", html + all_urls, re.IGNORECASE):
            add(
                "Google Analytics",
                "Analytics",
                0.95,
                "html_or_url",
                "Analytics marker",
                "Google Analytics script or global",
            )
        if re.search(r"connect\.facebook\.net|fbq\s*\(", html + all_urls, re.IGNORECASE):
            add("Meta Pixel", "Analytics", 0.95, "html_or_url", "Meta Pixel marker", "Meta Pixel script or call")
        if "hotjar" in html + all_urls:
            add("Hotjar", "Analytics", 0.95, "html_or_url", "Hotjar marker", "Hotjar script")
        if re.search(r"js\.stripe\.com|stripe\.js|stripe\s*\.", html + all_urls, re.IGNORECASE):
            add("Stripe", "Payments", 0.9, "html_or_url", "Stripe marker", "Stripe client script or global")

        # Hosting, CDN and web server signals.  These are infrastructure clues,
        # not proof of the application's backend framework.
        if re.search(r"cloudflare|cdnjs\.cloudflare\.com|cf-ray", html + all_urls + header_text, re.IGNORECASE):
            add(
                "Cloudflare",
                "CDN / Security",
                0.9,
                "url_or_header",
                "Cloudflare marker",
                "Cloudflare asset or response header",
            )
        if re.search(r"cloudfront\.net|cloudfront", all_urls + header_text, re.IGNORECASE):
            add(
                "Amazon CloudFront",
                "CDN",
                0.95,
                "url_or_header",
                "CloudFront marker",
                "CloudFront asset or response header",
            )
            add("Amazon Web Services", "Hosting", 0.8, "url_or_header", "AWS CloudFront", "AWS service hostname")
        elif re.search(r"amazonaws\.com|awsstatic\.com", all_urls, re.IGNORECASE):
            add(
                "Amazon Web Services",
                "Hosting",
                0.9,
                "resource_url",
                "amazonaws.com/awsstatic.com",
                "AWS service hostname",
            )
        if "vercel" in header_text or ".vercel.app" in all_urls:
            add("Vercel", "Hosting", 0.95, "url_or_header", "Vercel marker", "Vercel hostname or response header")
        if "netlify" in header_text or ".netlify.app" in all_urls:
            add("Netlify", "Hosting", 0.95, "url_or_header", "Netlify marker", "Netlify hostname or response header")

        server = headers.get("server", "")
        if re.search(r"\bnginx\b", server, re.IGNORECASE):
            add("Nginx", "Web server", 0.98, "response_header", server, "Server response header")
        if re.search(r"\bapache\b", server, re.IGNORECASE):
            add("Apache", "Web server", 0.98, "response_header", server, "Server response header")
        if re.search(r"\bmicrosoft-iis\b", server, re.IGNORECASE):
            add("Microsoft IIS", "Web server", 0.98, "response_header", server, "Server response header")

        # Backend signals are intentionally conservative.  These indicate a
        # server/runtime fingerprint, not definitive application framework use.
        if re.search(r"\buvicorn\b", server, re.IGNORECASE):
            add("Uvicorn", "Application server", 0.98, "response_header", server, "Uvicorn response header")
        django_cookie = next(
            (name for name in cookie_names if name in {"csrftoken", "django_language", "sessionid"}),
            None,
        )
        if django_cookie:
            add(
                "Django",
                "Backend framework",
                0.55,
                "cookie",
                f"cookie name: {django_cookie}",
                "Django-style cookie; backend inference",
            )
        if re.search(r"csrfmiddlewaretoken|django", html, re.IGNORECASE):
            add(
                "Django",
                "Backend framework",
                0.6,
                "html",
                "Django marker",
                "Django form or HTML marker; backend inference",
            )

        return self._merge(matches)

    @staticmethod
    def _merge(matches: Iterable[TechnologyMatch]) -> list[TechnologyMatch]:
        merged: dict[tuple[str, str], TechnologyMatch] = {}
        for match in matches:
            key = (match.name, match.category)
            current = merged.get(key)
            if current is None:
                merged[key] = match
                continue
            current.confidence = max(current.confidence, match.confidence)
            if current.version is None:
                current.version = match.version
            existing = {(item.source, item.value, item.detail) for item in current.evidence}
            current.evidence.extend(
                item for item in match.evidence if (item.source, item.value, item.detail) not in existing
            )
        return sorted(merged.values(), key=lambda item: (item.category.lower(), item.name.lower()))
