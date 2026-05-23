"""
CMS / Website Builder Detector
==============================
Multi-signal detection: HTTP headers → meta generator → HTML/URL signatures.
Covers ~15 platforms relevant to the Ukrainian/EU market.
"""

import re
import requests
from urllib.parse import urlparse

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Social media domains (detected without HTTP request) ──────────────────────
_SOCIAL_DOMAINS = (
    "instagram.com", "facebook.com", "fb.com", "t.me", "telegram.me",
    "tiktok.com", "linktr.ee", "ig.me", "twitter.com", "x.com",
    "youtube.com", "linkedin.com",
)

# ── CMS signature rules ──────────────────────────────────────────────────────
# Each rule: (label, check_function)
# check_function(headers_lower: dict, html: str) -> bool
#   headers_lower = {header_name_lower: header_value_lower}
#   html = full response text, already lowercased

def _h(headers, *keys):
    """Check if any key substring appears in any header value."""
    vals = " ".join(headers.values())
    return any(k in vals for k in keys)

def _m(html, *patterns):
    """Check if any pattern appears in html."""
    return any(p in html for p in patterns)


_CMS_RULES = [
    # ── Constructors & Builders ───────────────────────────────────────────────
    ("Tilda", lambda h, t: _m(t,
        "tildacdn", "tilda-blocks", "tilda-scripts", "tilda.cc",
        "t-body", "t-records", "t-container")),

    ("Wix", lambda h, t: _h(h, "x-wix") or _m(t,
        "wix.com", "parastorage.com", "_wix_browser_sess",
        "wix-warmup-data", "wixstatic.com")),

    ("Squarespace", lambda h, t: _m(t,
        "squarespace.com", "sqs-block", "sqs-layout",
        'name="generator" content="squarespace')),

    ("Weebly", lambda h, t: _m(t,
        "weebly.com", "wsite-", "weebly-footer")),

    ("Webflow", lambda h, t: _h(h, "webflow") or _m(t,
        "webflow.com", "w-webflow", "wf-page", "wf-section")),

    # ── E-commerce ────────────────────────────────────────────────────────────
    ("Shopify", lambda h, t: _h(h, "shopify") or _m(t,
        "cdn.shopify", "shopify.theme", "myshopify.com",
        "shopify-section")),

    ("OpenCart", lambda h, t: _m(t,
        "catalog/view/theme/", "route=product", "route=common",
        "opencart")),

    ("Horoshop", lambda h, t: _m(t,
        "horoshop.ua", "horoshop.com", "ho-product",
        "ho-catalog")),

    ("Prom.ua", lambda h, t: _m(t,
        "prom.ua", "ek-grid", "ek-text")),

    # ── CMS ───────────────────────────────────────────────────────────────────
    ("WordPress", lambda h, t: _m(t,
        "/wp-content/", "/wp-includes/", "wp-json",
        'name="generator" content="wordpress')),

    ("Joomla", lambda h, t: _h(h, "joomla") or _m(t,
        "/media/jui/", "option=com_",
        'name="generator" content="joomla')),

    ("Drupal", lambda h, t: _h(h, "x-drupal", "drupal") or _m(t,
        "/sites/default/files/", "drupal.js", "drupal.settings")),

    ("Bitrix", lambda h, t: _h(h, "bitrix") or _m(t,
        "/bitrix/", "bx-core", "bx.message", "1c-bitrix")),

    ("MODX", lambda h, t: _m(t,
        'name="generator" content="modx',
        "/assets/components/")),

    # ── JS Frameworks (detected as "custom" but with specifics) ───────────────
    ("Next.js", lambda h, t: _h(h, "x-nextjs", "x-powered-by: next") or _m(t,
        "__next_data__", "_next/static", "id=\"__next\"")),

    ("Nuxt.js", lambda h, t: _m(t,
        "__nuxt", "_nuxt/", "nuxt.config")),

    ("Gatsby", lambda h, t: _m(t,
        "gatsby-", "___gatsby", "/page-data/")),
]


def check_cms(url: str) -> str:
    """
    Detect the CMS / builder behind a website URL.

    Returns one of:
      - CMS name (e.g. "WordPress", "Tilda")
      - "Social Media"
      - "No Website"
      - "Error/Timeout"
      - "Error/Unreachable"
      - "Custom/Unknown"
    """
    if not url or not url.strip():
        return "No Website"

    url = url.strip()

    # ── 1. Social media short-circuit (no HTTP request) ───────────────────────
    try:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        domain = url.lower()

    for social in _SOCIAL_DOMAINS:
        if domain == social or domain.endswith("." + social):
            return "Social Media"

    # ── 2. HTTP request ───────────────────────────────────────────────────────
    headers_req = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    }

    try:
        response = requests.get(
            url,
            timeout=5,
            headers=headers_req,
            allow_redirects=True,
            verify=False,           # some small business sites have bad certs
        )
    except requests.exceptions.Timeout:
        return "Error/Timeout"
    except Exception:
        return "Error/Unreachable"

    html = response.text.lower()
    resp_headers = {k.lower(): v.lower() for k, v in response.headers.items()}

    # ── 3. Run detection rules ────────────────────────────────────────────────
    for label, check_fn in _CMS_RULES:
        try:
            if check_fn(resp_headers, html):
                return label
        except Exception:
            continue

    return "Custom/Unknown"