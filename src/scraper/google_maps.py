"""
Google Maps Lead Scraper
------------------------
Scrapes business lead data from Google Search's Local results panel
(the "tbm=lcl" endpoint). This approach avoids the heavy, JS-hydration-
dependent Google Maps SPA entirely — the local results page is rendered
server-side and is far more stable for automation.

Strategy
--------
1.  Navigate directly to the pre-built search URL with the query embedded.
2.  Handle the cookie consent banner (first run only).
3.  Parse all business cards on the current page.
4.  Follow the "Next" pagination button until we hit MAX_LEADS or run out of pages.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import urllib.parse
from typing import TypedDict

from playwright.async_api import BrowserContext, Page, async_playwright
from playwright_recaptcha import recaptchav2

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Stealth JavaScript
# ---------------------------------------------------------------------------
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', {
  get: () => [1,2,3,4,5].map(() => ({ length:0, item:()=>null, namedItem:()=>null })),
});
Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
window.chrome = { runtime: {} };
"""

# ---------------------------------------------------------------------------
# Data Schema
# ---------------------------------------------------------------------------


class BusinessLead(TypedDict):
    """Schema for a single parsed business entry from Google Search Local."""

    name: str | None
    full_address: str | None   # Street + city block (no rating/category)
    city: str | None           # Inferred from query or address tail
    phone: str | None
    website: str | None
    rating: str | None         # e.g. "4.5"
    reviews_count: str | None  # e.g. "312"
    category: str | None       # e.g. "Florist"
    query: str                 # The original search query


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------
# Google Search Local results use relatively stable semantic attributes.
# We deliberately avoid short obfuscated class names (e.g. "VkpSyc") which
# are compiled identifiers that change with every code push.

SELECTORS = {
    # Each business result card
    "card": "[data-cid], div[class*='mnr-c']",
    # Business name — inside a heading role element in the card
    "name": "[role='heading']",
    # Star rating — usually an img or span with aria-label "X stars"
    "rating": "[aria-label*='star'], [aria-label*='stars']",
    # Website: prefer the explicit "Website" aria-label link; fall back to any
    # external href that doesn't point back to Google properties.
    "website": (
        "a[aria-label='Website'], "
        "a:has-text('Website'), "
        "a[href^='http']:not([href*='google']):not([href*='maps'])"
    ),
    # Cookie consent accept button — English only (we force hl=en)
    "cookie_accept": (
        "button[aria-label*='Accept all'], "
        "button:has-text('Accept all'), "
        "button:has-text('I agree')"
    ),
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_LEADS = 500
PAGE_LOAD_WAIT = 2.5   # seconds to wait after navigation for the DOM to settle
NAVIGATION_TIMEOUT = 30_000  # ms

# Brands that are large chains / not useful SMB leads
BLACKLISTED_BRANDS: set[str] = {
    "silpo", "сільпо", "сильпо",
    "auchan", "ашан",
    "jysk",
    "varus", "варус",
    "metro",
    "novus",
    "atb", "атб",
    "epicentr", "епіцентр",
    "tsum", "цум",
    "gulliver",
    "comfy",
    "foxtrot",
    "eldorado",
}

# ---------------------------------------------------------------------------
# City Geolocation — used to override browser geolocation & Google params
# ---------------------------------------------------------------------------
# (latitude, longitude, country_code)
CITY_GEO: dict[str, tuple[float, float, str]] = {
    # Ukraine
    "kyiv": (50.4501, 30.5234, "ua"), "київ": (50.4501, 30.5234, "ua"),
    "lviv": (49.8397, 24.0297, "ua"), "львів": (49.8397, 24.0297, "ua"),
    "odesa": (46.4825, 30.7233, "ua"), "одеса": (46.4825, 30.7233, "ua"),
    "kharkiv": (49.9935, 36.2304, "ua"), "харків": (49.9935, 36.2304, "ua"),
    "dnipro": (48.4647, 35.0462, "ua"), "дніпро": (48.4647, 35.0462, "ua"),
    # Poland
    "warsaw": (52.2297, 21.0122, "pl"), "warszawa": (52.2297, 21.0122, "pl"),
    "krakow": (50.0647, 19.9450, "pl"), "kraków": (50.0647, 19.9450, "pl"),
    "wroclaw": (51.1079, 17.0385, "pl"), "wrocław": (51.1079, 17.0385, "pl"),
    "gdansk": (54.3520, 18.6466, "pl"), "gdańsk": (54.3520, 18.6466, "pl"),
    "poznan": (52.4064, 16.9252, "pl"), "poznań": (52.4064, 16.9252, "pl"),
    "katowice": (50.2649, 19.0238, "pl"),
    "lublin": (51.2465, 22.5684, "pl"),
    # UK
    "london": (51.5074, -0.1278, "gb"),
    "manchester": (53.4808, -2.2426, "gb"),
    "birmingham": (52.4862, -1.8904, "gb"),
    "edinburgh": (55.9533, -3.1883, "gb"),
    # Germany
    "berlin": (52.5200, 13.4050, "de"),
    "munich": (48.1351, 11.5820, "de"), "münchen": (48.1351, 11.5820, "de"),
    "hamburg": (53.5511, 9.9937, "de"),
    "frankfurt": (50.1109, 8.6821, "de"),
    # Czech
    "prague": (50.0755, 14.4378, "cz"), "praha": (50.0755, 14.4378, "cz"),
    "brno": (49.1951, 16.6068, "cz"),
    # Other
    "paris": (48.8566, 2.3522, "fr"),
    "rome": (41.9028, 12.4964, "it"), "roma": (41.9028, 12.4964, "it"),
    "madrid": (40.4168, -3.7038, "es"),
    "barcelona": (41.3874, 2.1686, "es"),
    "amsterdam": (52.3676, 4.9041, "nl"),
    "vienna": (48.2082, 16.3738, "at"), "wien": (48.2082, 16.3738, "at"),
    "bangkok": (13.7563, 100.5018, "th"),
    "new york": (40.7128, -74.0060, "us"),
    "los angeles": (34.0522, -118.2437, "us"),
    "istanbul": (41.0082, 28.9784, "tr"),
}


# ---------------------------------------------------------------------------
# GoogleMapsScraper
# ---------------------------------------------------------------------------


class GoogleMapsScraper:
    """
    Async scraper that collects business leads from Google Search Local results.

    Uses the ``tbm=lcl`` endpoint which is server-side rendered — no SPA
    hydration issues, no search bar interaction required.

    Parameters
    ----------
    headless : bool
        Run Chromium headlessly. Default ``False`` for debug visibility.

    Usage
    -----
    >>> scraper = GoogleMapsScraper(headless=False)
    >>> leads = await scraper.run(["Flower shop Kyiv", "Beauty Salon Lviv"])
    """

    def __init__(self, headless: bool = False) -> None:
        self.headless = headless

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    async def run(self, queries: list[str]) -> list[BusinessLead]:
        """
        Run a full scraping session for each query in *queries*.

        Returns a flat list of all leads found across all queries.
        """
        all_results: list[BusinessLead] = []
        seen_cids: set[str] = set()

        # Try to detect city from the first query for initial geolocation
        geo_info = self._detect_city_geo(queries[0] if queries else "")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            # Build context options with geolocation override
            ctx_opts = dict(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                timezone_id="America/New_York",
                permissions=["geolocation"],
            )
            if geo_info:
                lat, lon, _ = geo_info
                ctx_opts["geolocation"] = {"latitude": lat, "longitude": lon}
                logger.info("   📍 Browser geolocation set to %.4f, %.4f", lat, lon)

            context: BrowserContext = await browser.new_context(**ctx_opts)
            await context.add_init_script(_STEALTH_JS)

            for query in queries:
                # Update geolocation per-query if city changes
                query_geo = self._detect_city_geo(query)
                if query_geo and query_geo != geo_info:
                    lat, lon, _ = query_geo
                    await context.set_geolocation({"latitude": lat, "longitude": lon})
                    logger.info("   📍 Geolocation updated to %.4f, %.4f for '%s'", lat, lon, query)
                    geo_info = query_geo

                logger.info("🔍 Scraping query: '%s'", query)
                page: Page = await context.new_page()
                try:
                    leads = await self._scrape_query(page, query, seen_cids)
                    logger.info("   → %d leads collected for '%s'", len(leads), query)
                    all_results.extend(leads)
                except Exception as exc:  # noqa: BLE001
                    logger.error("   ✗ Query '%s' failed: %s", query, exc)
                    safe_name = query.replace(" ", "_")[:50]
                    try:
                        await page.screenshot(
                            path=f"debug_fail_{safe_name}.png", full_page=True
                        )
                        logger.info("   📸 Screenshot saved: debug_fail_%s.png", safe_name)
                    except Exception:
                        pass
                finally:
                    await page.close()

            await browser.close()

        return all_results

    @staticmethod
    def _detect_city_geo(query: str) -> tuple[float, float, str] | None:
        """Try to find a known city in the query string and return its geo data."""
        q_lower = query.lower()
        # Check exact words first, then substring match
        for city_name, geo in CITY_GEO.items():
            if city_name in q_lower:
                return geo
        return None

    # ------------------------------------------------------------------
    # Per-query orchestration
    # ------------------------------------------------------------------

    async def _scrape_query(
        self, page: Page, query: str, seen_cids: set[str]
    ) -> list[BusinessLead]:
        """
        Paginate through Google Local Search results for *query* by stepping
        through ``start=0, 20, 40, …`` URL parameters.

        URL-based pagination is unconditionally reliable — no DOM element
        clicking required.  If a page returns 0 leads we've hit the end.
        Leads are appended immediately so partial results survive any error.
        """
        leads: list[BusinessLead] = []
        results_per_page = 20
        max_pages = MAX_LEADS // results_per_page  # e.g. 25 pages for 500 leads

        first_page = True
        for page_num, start in enumerate(
            range(0, max_pages * results_per_page, results_per_page), start=1
        ):
            url = self._build_url(query, start=start)
            logger.info("   📄 Page %d → %s", page_num, url)
            await page.goto(url, timeout=NAVIGATION_TIMEOUT)

            # Handle cookie banner on the very first page only
            if first_page:
                await self._handle_cookie_banner(page)
                first_page = False

            # Let the DOM settle (lighter SPA than Maps, 2-3 s is enough)
            await asyncio.sleep(PAGE_LOAD_WAIT)

            # Parse all cards on this page
            page_leads = await self._parse_page(page, query, seen_cids)

            # Debug: always save a screenshot of the first page to see what's going on
            if start == 0:
                screenshot_path = f"debug_page_{query.replace(' ', '_')[:30]}.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                logger.info("   📸 Debug screenshot saved: %s", screenshot_path)

            # Persist immediately — even if an exception occurs later we keep
            leads.extend(page_leads)
            logger.info(
                "   ✓ Page %d: +%d leads (running total: %d)",
                page_num, len(page_leads), len(leads),
            )

            if not page_leads:
                # Empty page = end of results or CAPTCHA wall — stop early
                logger.info("   ✅ Empty page — all results collected.")
                break

            if len(leads) >= MAX_LEADS:
                logger.info("   ✅ Reached MAX_LEADS cap (%d).", MAX_LEADS)
                break

            # Human-like random delay between page loads to avoid rate-limiting
            delay = random.uniform(3.0, 7.0)
            logger.debug("   💤 Waiting %.1f s before next page…", delay)
            await asyncio.sleep(delay)

        return leads[:MAX_LEADS]

    # ------------------------------------------------------------------
    # URL builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_url(query: str, start: int = 0) -> str:
        """Build a Google Search Local results URL for the given query."""
        params = {
            "q": query,
            "tbm": "lcl",    # Local results tab
            "hl": "en",      # Force English interface
            "start": start,  # Pagination offset (20 per page)
        }

        # Add country override so Google doesn't bias by IP geolocation
        q_lower = query.lower()
        for city_name, (_, _, country_code) in CITY_GEO.items():
            if city_name in q_lower:
                params["gl"] = country_code  # e.g. "gb" for London
                params["near"] = city_name.title()  # hint the city
                break

        return "https://www.google.com/search?" + urllib.parse.urlencode(params)

    # ------------------------------------------------------------------
    # Page parser
    # ------------------------------------------------------------------

    async def _parse_page(
        self, page: Page, query: str, seen_cids: set[str]
    ) -> list[BusinessLead]:
        """Extract all business cards visible on the current search results page."""
        cards = page.locator(SELECTORS["card"])
        count = await cards.count()
        logger.info("   🔍 Found %d card elements with selector '%s'", count, SELECTORS["card"])

        if count == 0:
            # Fallback: dump the page title so we can diagnose CAPTCHA / redirects
            title = await page.title()
            logger.info("   ℹ️ Page title: '%s'", title)
            
            # Detect CAPTCHA / Block
            content = await page.content()
            if "Before you continue" in title or "Consent" in title:
                logger.warning("   ⚠️ Possibly stuck on a consent page.")
            elif "unusual traffic" in content.lower() or "captcha-delivery" in content.lower():
                logger.error("   ⛔ CAPTCHA / Block detected! Attempting to solve...")
                # Save as a specific failure screenshot before solving
                await page.screenshot(path="debug_BLOCK_PRE_SOLVE.png", full_page=True)
                
                if await self._solve_captcha(page):
                    logger.info("   🎉 CAPTCHA solved successfully! Reloading page...")
                    await page.reload(wait_until="domcontentloaded")
                    # Re-parse the page after reload
                    return await self._parse_page(page, query, seen_cids)
                else:
                    logger.error("   ❌ Failed to solve CAPTCHA automatically.")
                    await page.screenshot(path="debug_BLOCK_FAILED_SOLVE.png", full_page=True)

        leads: list[BusinessLead] = []
        for i in range(count):
            card = cards.nth(i)
            # Use data-cid as a stable unique identifier to prevent duplicates
            cid = await card.get_attribute("data-cid") or f"idx-{i}"
            if cid in seen_cids:
                continue
            seen_cids.add(cid)

            try:
                lead = await self._parse_card(card, query)
                name = lead["name"] or ""
                # Skip if no name, or the business is a blacklisted chain
                if name:
                    name_low = name.lower()
                    is_blacklisted = name_low in BLACKLISTED_BRANDS or any(
                        brand in name_low for brand in BLACKLISTED_BRANDS
                    )
                    if not is_blacklisted:
                        leads.append(lead)
                    else:
                        logger.debug("   ⏭️ Skipping blacklisted: %s", name)
                else:
                    logger.debug("   ⏭️ Skipping result with no name (likely an ad or empty)")
            except Exception as exc:  # noqa: BLE001
                logger.debug("   Card %d error: %s", i, exc)

        return leads

    # ------------------------------------------------------------------
    # Card parser
    # ------------------------------------------------------------------

    async def _parse_card(self, card, query: str) -> BusinessLead:
        """
        Extract clean, structured data from a single Google Local result card.
        Every field is individually guarded — missing data returns None.
        """
        lead: BusinessLead = {
            "name": None,
            "full_address": None,
            "city": None,
            "phone": None,
            "website": None,
            "rating": None,
            "reviews_count": None,
            "category": None,
            "query": query,
        }

        # Infer city from the last word(s) of the query (e.g. "Flower shop Kyiv" → "Kyiv")
        query_parts = query.rsplit(" ", 1)
        if len(query_parts) == 2:
            lead["city"] = query_parts[-1].strip()

        # ── Collect the full plain-text of the card once ──────────────────
        try:
            full_text: str = await card.inner_text()
        except Exception:
            full_text = ""

        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

        # ── Name ─────────────────────────────────────────────────────────
        try:
            heading = card.locator(SELECTORS["name"]).first
            if await heading.count() > 0:
                lead["name"] = (await heading.inner_text()).strip() or None
        except Exception:
            pass

        # ── Website ──────────────────────────────────────────────────────
        # Google Local renders an explicit link labelled "Website" when available.
        try:
            website_el = card.locator(SELECTORS["website"]).first
            if await website_el.count() > 0:
                href = await website_el.get_attribute("href")
                # Strip Google's redirect wrapper if present
                if href and "google.com/url" in href:
                    m = re.search(r"[?&]q=([^&]+)", href)
                    href = m.group(1) if m else href
                lead["website"] = href or None
        except Exception:
            pass

        # ── Phone (regex over all visible text lines) ────────────────────
        # Matches international formats: +380 93 090 0999, +1-800-555-0199, etc.
        _PHONE_RE = re.compile(
            r"\+?\d[\d\s\-\.\(\)]{6,18}\d"
        )
        for line in lines:
            if lead["phone"] is None:
                m = _PHONE_RE.fullmatch(line.strip())
                if m:
                    lead["phone"] = m.group(0).strip()
                    break

        # ── Parse composite info lines like "4.5(312) · Florist" ────────
        # Also handles "Velyka Vasylkivska St, 132 · +380 93 ..." and
        # pure category strings like "Florist".
        for line in lines:
            line = line.strip()
            # If the line is just the business name, ignore it for composite parsing
            if lead["name"] and line.lower() == lead["name"].lower():
                continue
            
            # Filter out status indicators that often look like categories/addresses
            if line.lower() in ("closed", "open 24 hours", "opening soon", "permanently closed"):
                continue

            parsed = self._parse_composite_line(line)
            if parsed["rating"] and lead["rating"] is None:
                lead["rating"] = parsed["rating"]
            if parsed["reviews_count"] and lead["reviews_count"] is None:
                lead["reviews_count"] = parsed["reviews_count"]
            if parsed["category"] and lead["category"] is None:
                lead["category"] = parsed["category"]
            if parsed["address"] and lead["full_address"] is None:
                lead["full_address"] = parsed["address"]

        return lead

    # ------------------------------------------------------------------
    # Composite line parser
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_composite_line(line: str) -> dict:
        """
        Parse a Google Local result summary line into its components.

        Handles the following layouts (all observed in the wild):
        - ``4.5(312) · Florist``
        - ``4.5 (1.2K) · Flower delivery``
        - ``Площа Слави, 1 · +380 99 512 7829``
        - ``Kostiantynivska St, 57``
        - ``Florist``
        """
        result = {"rating": None, "reviews_count": None, "category": None, "address": None}

        # Pattern A: "4.5(312) · Category" or "4.5 (1.2K) ..."
        m = re.match(
            r"^(\d\.\d)\s*\(([\d\.]+K?)\)\s*[·\-]?\s*(.+)?$",
            line.strip(),
        )
        if m:
            result["rating"] = m.group(1)
            result["reviews_count"] = m.group(2)
            tail = (m.group(3) or "").strip().strip("·").strip()
            if tail:
                result["category"] = tail
            return result

        # Pattern B: "Street address [· something]"
        # A line is considered an address if it contains digits and looks street-like.
        _ADDR_RE = re.compile(
            r"(?:\w+\.?\s+\d+|,\s*\d+|St\b|Ave\b|Blvd\b|ул\.|вул\.|просп\.)",
            re.IGNORECASE
        )
        if _ADDR_RE.search(line) and not any(k in line.lower() for k in ("stars", "reviews", "+")):
            # Strip trailing phone part if present
            address_part = line.split("·")[0].strip()
            # If it's too short, it's likely not a full address
            if len(address_part) > 6:
                result["address"] = address_part or None
                return result

        # Pattern C: pure category string (no digits, no punctuation, reasonable length)
        # We ensure it doesn't look like a status (Closed/Open) or a phone/rating line.
        if not any(c.isdigit() for c in line) and 4 <= len(line) <= 40:
            if "·" not in line and "," not in line:
                result["category"] = line.strip()

        return result

    async def _solve_captcha(self, page: Page) -> bool:
        """
        Attempts to solve Google's reCAPTCHA v2 using audio solver.
        Requires ffmpeg and playwright-recaptcha.
        """
        try:
            async with recaptchav2.AsyncSolver(page) as solver:
                await solver.solve_recaptcha()
            return True
        except Exception as exc:
            logger.error("   CAPTCHA Solver error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Cookie banner handler
    # ------------------------------------------------------------------

    async def _handle_cookie_banner(self, page: Page) -> None:
        """
        Accept Google's cookie consent banner if it appears.
        Non-blocking — silently continues if absent.
        """
        try:
            btn = page.locator(SELECTORS["cookie_accept"]).first
            await btn.click(timeout=5_000)
            logger.info("   ✅ Cookie banner accepted.")
        except Exception:
            logger.info("   ℹ️ Cookie banner not found, proceeding.")


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main() -> None:
        queries = ["Flower shop Kyiv", "Beauty Salon Lviv"]
        scraper = GoogleMapsScraper(headless=False)
        results = await scraper.run(queries)

        import json
        print(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"\nTotal leads found: {len(results)}")

    asyncio.run(main())
