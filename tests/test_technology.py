"""Browser-free tests for local technology fingerprinting."""

from __future__ import annotations

import json

from formharvester.technology import PageSignals, TechnologyDetector


def names(signals: PageSignals) -> set[str]:
    return {match.name for match in TechnologyDetector().detect(signals)}


def test_detects_frameworks_platforms_and_infrastructure() -> None:
    signals = PageSignals(
        url="https://example.com",
        html=(
            '<meta name="generator" content="WordPress 6.5">'
            '<div id="__next"></div>'
            '<script src="https://cdn.example.com/_next/static/chunks/app.js"></script>'
            '<script src="https://cdn.example.com/jquery-3.7.1.min.js"></script>'
        ),
        headers={"server": "nginx", "x-vercel-id": "iad1::abc"},
        scripts=["https://cdn.example.com/_next/static/chunks/app.js", "https://cdn.example.com/jquery-3.7.1.min.js"],
    )

    assert {"WordPress", "Next.js", "jQuery", "Nginx", "Vercel"} <= names(signals)
    jquery = next(match for match in TechnologyDetector().detect(signals) if match.name == "jQuery")
    assert jquery.version == "3.7.1"
    assert jquery.evidence[0].source == "resource_url"


def test_backend_frameworks_are_reported_as_inferences() -> None:
    signals = PageSignals(
        html='<form><input type="hidden" name="csrfmiddlewaretoken" value="token"></form>',
        cookies=["csrftoken=abc"],
    )

    django = next(match for match in TechnologyDetector().detect(signals) if match.name == "Django")
    assert django.confidence < 0.7
    assert "inference" in django.evidence[0].detail
    assert "abc" not in django.evidence[0].value


def test_detector_merges_duplicate_signals() -> None:
    signals = PageSignals(
        html='<script src="https://cdn.shopify.com/shopify.js"></script>',
        scripts=["https://cdn.shopify.com/shopify.js"],
        js_globals={"Shopify"},
    )

    matches = TechnologyDetector().detect(signals)
    shopify = [match for match in matches if match.name == "Shopify"]
    assert len(shopify) == 1
    assert len(shopify[0].evidence) == 1


def test_match_serializes_to_json() -> None:
    signals = PageSignals(html='<script src="https://js.stripe.com/v3"></script>')
    match = next(match for match in TechnologyDetector().detect(signals) if match.name == "Stripe")

    payload = json.dumps(match.to_dict())
    assert '"name": "Stripe"' in payload
    assert '"evidence"' in payload


class _Driver:
    current_url = "https://example.com/contact/"
    page_source = '<meta name="generator" content="WordPress">'

    def execute_script(self, _script: str) -> dict[str, object]:
        return {
            "scripts": ["https://cdn.example.com/jquery-3.7.1.min.js"],
            "stylesheets": [],
            "cookies": ["csrftoken=abc"],
            "meta": {"generator": ["WordPress"]},
            "jsGlobals": [],
            "resources": ["https://cdn.example.com/_next/static/app.js"],
        }

    def get_log(self, _kind: str) -> list[dict[str, str]]:
        return [
            {
                "message": json.dumps(
                    {
                        "message": {
                            "method": "Network.responseReceived",
                            "params": {
                                "response": {
                                    "url": self.current_url,
                                    "headers": {"Server": "nginx"},
                                }
                            },
                        }
                    }
                )
            }
        ]


def test_from_driver_collects_browser_signals_defensively() -> None:
    signals = TechnologyDetector.from_driver(_Driver())

    assert signals.url.endswith("/contact/")
    assert "https://cdn.example.com/jquery-3.7.1.min.js" in signals.scripts
    assert "generator" in signals.meta
    assert "csrftoken=abc" in signals.cookies
    assert signals.headers["server"] == "nginx"
