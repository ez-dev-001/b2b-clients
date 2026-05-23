"""
Email & Social Media Finder — waterfall approach.
==================================================
Email:   Google Maps → mailto: → site crawl.
Socials: Google Maps website field → <a href> from HTML.
"""

import re
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ────────────────────────────────────────────────────────────────────

_TIMEOUT = 4
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Pages to crawl for email (in priority order)
_CONTACT_SLUGS = ["/contact", "/contacts", "/contact-us", "/contactus",
                  "/kontakt", "/kontakty", "/kontakti",
                  "/get-in-touch", "/reach-us",
                  "/about", "/about-us", "/pro-nas"]

# Domains to skip (social media, not real websites)
_SOCIAL_DOMAINS = {
    "instagram.com", "facebook.com", "fb.com", "t.me", "telegram.me",
    "tiktok.com", "twitter.com", "x.com", "youtube.com", "linktr.ee",
    "ig.me", "vk.com", "linkedin.com", "pinterest.com",
}

# Email patterns to IGNORE (generic, not real contacts)
_JUNK_PATTERNS = {
    "example.com", "sentry.io", "wixpress.com",
    "email.com", "your-email", "youremail", "test.com",
    "domain.com", "company.com", "website.com",
}

_JUNK_PREFIXES = {"noreply", "no-reply", "mailer-daemon", "postmaster",
                  "webmaster", "root", "abuse"}

# File extensions that are NOT emails
_FILE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
                    ".css", ".js", ".pdf", ".woff", ".woff2", ".ttf"}


# ── Email validation ─────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)


def _is_valid_email(email: str) -> bool:
    """Filter out junk/fake emails."""
    email = email.lower().strip()

    # Too short or too long
    if len(email) < 6 or len(email) > 100:
        return False

    # File extension disguised as email
    if any(email.endswith(ext) for ext in _FILE_EXTENSIONS):
        return False

    # Junk domains
    domain = email.split("@")[1] if "@" in email else ""
    if any(junk in domain for junk in _JUNK_PATTERNS):
        return False

    # Junk prefixes
    local = email.split("@")[0] if "@" in email else ""
    if local in _JUNK_PREFIXES:
        return False

    return True


def _is_social(url: str) -> bool:
    """Return True if the URL points to a social media profile."""
    try:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return False
    return any(domain == s or domain.endswith("." + s) for s in _SOCIAL_DOMAINS)


def _fetch(url: str) -> str | None:
    """Quick GET, return HTML text or None."""
    try:
        resp = requests.get(url, timeout=_TIMEOUT, verify=False,
                            headers=_HEADERS, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text[:50_000]  # limit to 50KB
    except Exception:
        pass
    return None


# ── Method 1: Google Maps ─────────────────────────────────────────────────────

def _find_from_gmaps(lead: dict) -> str | None:
    """Check if the scraper already collected an email from Google Maps."""
    # Some Google Maps profiles show email in the detail panel
    email = lead.get("email")
    if email and _is_valid_email(email):
        return email
    return None


# ── Method 2: mailto: links ──────────────────────────────────────────────────

def _find_from_mailto(html: str) -> str | None:
    """Parse <a href="mailto:..."> from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if href.startswith("mailto:"):
            raw = href.replace("mailto:", "").split("?")[0].strip()
            if _is_valid_email(raw):
                return raw
    return None


# ── Method 3: Regex crawl ────────────────────────────────────────────────────

def _find_from_regex(html: str) -> str | None:
    """Extract emails via regex from HTML text."""
    # Remove script/style tags to avoid JS emails
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)

    emails = _EMAIL_RE.findall(text)
    for email in emails:
        if _is_valid_email(email):
            return email
    return None


# ── Social Media Extraction ──────────────────────────────────────────────────

# Map domain fragments → field name
_SOCIAL_MAP = {
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "t.me": "telegram",
    "telegram.me": "telegram",
    "tiktok.com": "tiktok",
}


def _normalize_social_url(url: str) -> str | None:
    """Clean up a social media URL. Return None if it's a generic root link."""
    url = url.strip().rstrip("/")
    # Skip share/sharer/intent links
    if any(x in url for x in ["/sharer", "/share?", "/intent/", "/dialog/"]):
        return None
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    # Skip root links like "https://instagram.com" with no profile
    if not path:
        return None
    return url


def _extract_socials_from_url(url: str) -> dict:
    """If the GMaps website field IS a social link, extract it."""
    result = {}
    if not url:
        return result
    try:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return result
    for social_domain, field in _SOCIAL_MAP.items():
        if domain == social_domain or domain.endswith("." + social_domain):
            cleaned = _normalize_social_url(url)
            if cleaned:
                result[field] = cleaned
            break
    return result


def _extract_socials_from_html(html: str) -> dict:
    """Parse <a href> tags for social media links."""
    result = {}
    soup = BeautifulSoup(html, "html.parser")
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not href.startswith("http"):
            continue
        try:
            domain = urlparse(href).netloc.lower().removeprefix("www.")
        except Exception:
            continue
        for social_domain, field in _SOCIAL_MAP.items():
            if (domain == social_domain or domain.endswith("." + social_domain)) and field not in result:
                cleaned = _normalize_social_url(href)
                if cleaned:
                    result[field] = cleaned
                break
    return result


# ── Main function ─────────────────────────────────────────────────────────────

def find_email(lead: dict) -> tuple[str | None, str | None, dict]:
    """
    Waterfall email + social media finder for a lead.

    Returns (email, source, socials) where:
    - source is "google_maps", "mailto", "site_crawl", or None
    - socials is {"instagram": "...", "facebook": "...", ...}
    """
    socials: dict = {}

    # ── Socials from GMaps website field ──
    website = lead.get("website")
    if website:
        socials.update(_extract_socials_from_url(website))

    # ── Method 1: Google Maps email data ──
    email = _find_from_gmaps(lead)
    if email:
        return email, "google_maps", socials

    # ── Get website URL ──
    if not website or _is_social(website):
        return None, None, socials

    # Normalize URL
    if not website.startswith("http"):
        website = "https://" + website

    # ── Method 2: mailto: on homepage ──
    homepage_html = _fetch(website)
    if homepage_html:
        # Extract socials from HTML (zero extra requests)
        socials.update(_extract_socials_from_html(homepage_html))

        email = _find_from_mailto(homepage_html)
        if email:
            return email, "mailto", socials

    # ── Method 3: Crawl contact pages + regex ──
    if homepage_html:
        email = _find_from_regex(homepage_html)
        if email:
            return email, "site_crawl", socials

    # Then try contact/about pages
    base = f"{urlparse(website).scheme}://{urlparse(website).netloc}"
    for slug in _CONTACT_SLUGS:
        page_url = urljoin(base, slug)
        html = _fetch(page_url)
        if html:
            # Also extract socials from subpages
            socials.update(_extract_socials_from_html(html))

            email = _find_from_mailto(html)
            if email:
                return email, "mailto", socials
            email = _find_from_regex(html)
            if email:
                return email, "site_crawl", socials

    return None, None, socials
