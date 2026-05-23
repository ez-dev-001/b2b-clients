"""
Language Detector — determine lead's preferred language.
=========================================================
Priority 1: HTML `lang` attribute from the website.
Priority 2: City-based mapping from the scraper query.
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ── Lang code → full name ─────────────────────────────────────────────────────

LANG_CODE_MAP: dict[str, str] = {
    "uk": "Ukrainian",
    "ua": "Ukrainian",     # non-standard but common
    "pl": "Polish",
    "en": "English",
    "ru": "Russian",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "cs": "Czech",
    "sk": "Slovak",
    "ro": "Romanian",
    "hu": "Hungarian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "th": "Thai",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "tr": "Turkish",
    "vi": "Vietnamese",
}


# ── City → language mapping ───────────────────────────────────────────────────

CITY_LANG_MAP: dict[str, str] = {
    # Ukraine
    "kyiv": "Ukrainian", "київ": "Ukrainian",
    "lviv": "Ukrainian", "львів": "Ukrainian",
    "odesa": "Ukrainian", "одеса": "Ukrainian",
    "kharkiv": "Ukrainian", "харків": "Ukrainian",
    "dnipro": "Ukrainian", "дніпро": "Ukrainian",
    "zaporizhzhia": "Ukrainian", "запоріжжя": "Ukrainian",
    "vinnytsia": "Ukrainian", "вінниця": "Ukrainian",

    # Poland
    "warsaw": "Polish", "warszawa": "Polish",
    "krakow": "Polish", "kraków": "Polish",
    "wroclaw": "Polish", "wrocław": "Polish",
    "gdansk": "Polish", "gdańsk": "Polish",
    "poznan": "Polish", "poznań": "Polish",
    "lodz": "Polish", "łódź": "Polish",
    "katowice": "Polish",
    "lublin": "Polish",
    "szczecin": "Polish",

    # Germany
    "berlin": "German", "munich": "German", "münchen": "German",
    "hamburg": "German", "frankfurt": "German", "cologne": "German",
    "köln": "German", "düsseldorf": "German", "stuttgart": "German",

    # Czech Republic
    "prague": "Czech", "praha": "Czech", "brno": "Czech",

    # Other
    "bangkok": "Thai",
    "london": "English",
    "new york": "English",
    "los angeles": "English",
    "paris": "French",
    "rome": "Italian", "roma": "Italian",
    "madrid": "Spanish", "barcelona": "Spanish",
    "lisbon": "Portuguese", "lisboa": "Portuguese",
    "amsterdam": "Dutch",
    "vienna": "German", "wien": "German",
    "budapest": "Hungarian",
    "bucharest": "Romanian", "bucurești": "Romanian",
    "bratislava": "Slovak",
    "istanbul": "Turkish",
}


# ── Social media short-circuit ────────────────────────────────────────────────

_SOCIAL_DOMAINS = (
    "instagram.com", "facebook.com", "fb.com", "t.me", "telegram.me",
    "tiktok.com", "twitter.com", "x.com", "youtube.com", "linktr.ee",
    "ig.me", "vk.com",
)


def _is_social(url: str) -> bool:
    """Return True if the URL points to a social media profile."""
    try:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return False
    return any(domain == s or domain.endswith("." + s) for s in _SOCIAL_DOMAINS)


# ── Main function ─────────────────────────────────────────────────────────────

def determine_lead_language(website_url: str | None, city: str) -> str:
    """
    Detect the language a cold email should be written in.

    Priority 1: <html lang="..."> from the website.
    Priority 2: City-based mapping.
    Fallback:   "English".
    """

    # --- Priority 1: website HTML lang ---
    if website_url and not _is_social(website_url):
        try:
            resp = requests.get(
                website_url,
                timeout=3,
                verify=False,
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True,
            )
            soup = BeautifulSoup(resp.text[:4096], "html.parser")  # only parse head
            html_tag = soup.find("html")

            if html_tag:
                lang_attr = (html_tag.get("lang") or "").strip().lower()
                # Normalize: "uk-UA" → "uk", "pl-PL" → "pl"
                lang_code = lang_attr.split("-")[0] if lang_attr else ""
                if lang_code in LANG_CODE_MAP:
                    return LANG_CODE_MAP[lang_code]
        except Exception:
            pass  # fall through to city mapping

    # --- Priority 2: city mapping ---
    city_lower = city.strip().lower()

    # Direct match
    if city_lower in CITY_LANG_MAP:
        return CITY_LANG_MAP[city_lower]

    # Substring match: try to find a known city inside the query string
    # e.g. "Flower shop Kyiv" → find "kyiv"
    for known_city, lang in CITY_LANG_MAP.items():
        if known_city in city_lower:
            return lang

    return "English"
