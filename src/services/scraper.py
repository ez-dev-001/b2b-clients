import asyncio
import re
from typing import List, Dict
from playwright.async_api import async_playwright

# Stealth JavaScript
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', {
  get: () => [1,2,3,4,5].map(() => ({ length:0, item:()=>null, namedItem:()=>null })),
});
Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en', 'uk', 'ru'] });
window.chrome = { runtime: {} };
"""

# Blacklist of giant corporate chains to avoid indexing
GIANT_CHAINS_BLACKLIST = (
    "novus", "сільпо", "сильпо", "ашан", "auchan", "атб", "atb", 
    "епіцентр", "эпицентр", "epicentr", "розетка", "rozetka", 
    "eva", "watsons", "prostor", "укрпошта", "ukrposhta", "нова пошта", "nova poshta",
    "фора", "fora", "велика кишеня", "metro", "метро",
    "mcdonald's", "макдональдс", "макдональдз", "kfc", "пузата хата",
    "окко", "okko", "wog", "upg", "socar", "авіас", "klo",
    "приватбанк", "privatbank", "ощадбанк", "monobank",
    "аптека антс", "аптека доброго дня", "подорожник", "аптека 911","avrora","аврора"
)

# Alphabets for suffix-based query expansion
UKRAINIAN_ALPHABET = list("абвгґдеєжзиіїйклмнопрстуфхцчшщюя")
ENGLISH_ALPHABET = list("abcdefghijklmnopqrstuvwxyz")

# City coordinates for geolocation override
# (latitude, longitude, country_code)
CITY_GEO: dict[str, tuple[float, float, str]] = {
    "kyiv": (50.4501, 30.5234, "ua"), "київ": (50.4501, 30.5234, "ua"),
    "lviv": (49.8397, 24.0297, "ua"), "львів": (49.8397, 24.0297, "ua"),
    "odesa": (46.4825, 30.7233, "ua"), "одеса": (46.4825, 30.7233, "ua"),
    "kharkiv": (49.9935, 36.2304, "ua"), "харків": (49.9935, 36.2304, "ua"),
    "dnipro": (48.4647, 35.0462, "ua"), "дніпро": (48.4647, 35.0462, "ua"),
    "warsaw": (52.2297, 21.0122, "pl"), "warszawa": (52.2297, 21.0122, "pl"),
    "krakow": (50.0647, 19.9450, "pl"), "kraków": (50.0647, 19.9450, "pl"),
    "wroclaw": (51.1079, 17.0385, "pl"), "wrocław": (51.1079, 17.0385, "pl"),
    "gdansk": (54.3520, 18.6466, "pl"), "gdańsk": (54.3520, 18.6466, "pl"),
    "poznan": (52.4064, 16.9252, "pl"), "poznań": (52.4064, 16.9252, "pl"),
    "katowice": (50.2649, 19.0238, "pl"), "lublin": (51.2465, 22.5684, "pl"),
    "london": (51.5074, -0.1278, "gb"), "manchester": (53.4808, -2.2426, "gb"),
    "birmingham": (52.4862, -1.8904, "gb"), "edinburgh": (55.9533, -3.1883, "gb"),
    "berlin": (52.5200, 13.4050, "de"), "munich": (48.1351, 11.5820, "de"),
    "hamburg": (53.5511, 9.9937, "de"), "frankfurt": (50.1109, 8.6821, "de"),
    "prague": (50.0755, 14.4378, "cz"), "brno": (49.1951, 16.6068, "cz"),
    "paris": (48.8566, 2.3522, "fr"), "amsterdam": (52.3676, 4.9041, "nl"),
    "rome": (41.9028, 12.4964, "it"), "madrid": (40.4168, -3.7038, "es"),
    "barcelona": (41.3874, 2.1686, "es"), "vienna": (48.2082, 16.3738, "at"),
    "bangkok": (13.7563, 100.5018, "th"), "istanbul": (41.0082, 28.9784, "tr"),
    "new york": (40.7128, -74.0060, "us"), "los angeles": (34.0522, -118.2437, "us"),
}


def _detect_city_geo(query: str) -> tuple | None:
    """Find a known city in the query and return (lat, lon, country_code)."""
    q_lower = query.lower()
    for city_name, geo in CITY_GEO.items():
        if city_name in q_lower:
            return geo
    return None


def _expand_queries_alphabetical(queries: List[str]) -> List[str]:
    """Returns a list of queries with alphabetical suffixes."""
    expanded: List[str] = []
    
    for q in queries:
        # 1. Provide the exact original query first 
        expanded.append(q)
        
        # 2. Iterate over the Ukrainian/Cyrillic alphabet
        for letter in UKRAINIAN_ALPHABET:
            expanded.append(f"{q} {letter}")
            
        # 3. Iterate over the Latin/English alphabet
        for letter in ENGLISH_ALPHABET:
            expanded.append(f"{q} {letter}")
            
    return expanded


class GoogleMapsScraper:
    def __init__(self, headless: bool = False):
        self.base_url = "https://www.google.com/maps/search/"
        self.headless = headless

    async def scrape_queries(self, queries: List[str], max_results: int = 500) -> List[Dict]:
        all_leads = []

        # Dynamically append alphabetical suffixes to bypass ~120 results limit
        expanded_queries = _expand_queries_alphabetical(queries)
        print(f"🔄 Кластеризація Алфавітом: {len(queries)} базових запитів розширено до {len(expanded_queries)} запитів")

        # Detect geolocation from first query 
        geo_info = _detect_city_geo(queries[0]) if queries else None

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ]
            )

            # Build context with stealth options
            ctx_opts: dict = {
                "locale": "uk-UA", 
                "permissions": ["geolocation"],
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "viewport": {"width": 1440, "height": 900}
            }
            if geo_info:
                lat, lon, _ = geo_info
                ctx_opts["geolocation"] = {"latitude": lat, "longitude": lon}
                print(f"📍 Геолокація: {lat:.4f}, {lon:.4f}")

            context = await browser.new_context(**ctx_opts)
            await context.add_init_script(_STEALTH_JS)
            page = await context.new_page()

            for query_text in expanded_queries:
                if len(all_leads) >= max_results:
                    print(f"✅ Досягнуто ліміт лідів ({max_results}). Зупиняємо збір.")
                    break

                # Update geolocation per-query to open map over correct general area
                query_geo = _detect_city_geo(query_text)
                if query_geo and query_geo != geo_info:
                    lat, lon, _ = query_geo
                    await context.set_geolocation({"latitude": lat, "longitude": lon})
                    print(f"📍 Геолокація оновлена: {lat:.4f}, {lon:.4f} ({query_text})")
                    geo_info = query_geo
                    
                current_geo = query_geo or geo_info

                print(f"🔎 Пошук: {query_text}...")
                
                # We revert to normal URL but can add a standard zoom to focus the initial search
                if current_geo:
                    lat, lon, *_ = current_geo
                    map_url = f"{self.base_url}{query_text.replace(' ', '+')}/@{lat},{lon},13z"
                else:
                    map_url = f"{self.base_url}{query_text.replace(' ', '+')}"
                    
                await page.goto(map_url)

                feed_sel = 'div[role="feed"]'
                try:
                    await page.wait_for_selector(feed_sel, timeout=10000)
                except:
                    print(f"❌ Не вдалося завантажити результати")
                    continue

                # Обхід Cookies
                try:
                    btn = page.locator('button:has-text("Прийняти все"), button:has-text("Accept all")')
                    if await btn.count() > 0: await btn.first.click()
                except: pass

                # 1. ТУРБО-СКРОЛІНГ
                print("Скролимо...")
                feed = page.locator(feed_sel)
                last_h = await feed.evaluate("el => el.scrollHeight")
                while True:
                    await feed.evaluate("el => el.scrollBy(0, 5000)")
                    try:
                        await page.wait_for_function(f"document.querySelector('{feed_sel}').scrollHeight > {last_h}", timeout=2000)
                    except: pass
                    new_h = await feed.evaluate("el => el.scrollHeight")
                    if new_h == last_h: break
                    last_h = new_h

                # 2. НАДІЙНИЙ ЗБІР ДАНИХ
                place_links = await page.locator('a[href*="/maps/place/"]').all()
                # Apply per-query cap so total stays within max_results
                per_query_cap = max(1, max_results - len(all_leads))
                place_links = place_links[:per_query_cap]
                total = len(place_links)
                print(f"✅ Знайдено {total} об'єктів. Збираємо контакти та відгуки...")

                for index, link in enumerate(place_links, 1):
                    try:
                        name = await link.get_attribute('aria-label')
                        url = await link.get_attribute('href')
                        
                        # 1. Deduplication check
                        if not name or any(l["place_url"] == url for l in all_leads): 
                            continue

                        # 2. Giant Business Blacklist check
                        name_lower = name.lower()
                        if any(chain in name_lower for chain in GIANT_CHAINS_BLACKLIST):
                            print(f"   ⏩ Пропускаємо гіганта: {name}")
                            continue

                        # КЛІК В КАРТОЧКУ
                        await link.click()
                        await asyncio.sleep(2)

                        # --- ЗБІР КОНТАКТІВ ---
                        addr_el = page.locator('button[data-item-id="address"]')
                        address = await addr_el.first.inner_text() if await addr_el.count() > 0 else None

                        phone_el = page.locator('button[data-item-id^="phone:"]')
                        phone = await phone_el.first.inner_text() if await phone_el.count() > 0 else None

                        site_el = page.locator('a[data-item-id="authority"]')
                        website = await site_el.first.get_attribute('href') if await site_el.count() > 0 else None

# --- ЗБІР ВІДГУКІВ ---
                        review_texts = []
                        seen_reviews = set() # Секретна зброя проти дублікатів

                        try:
                            # 1. Відкриваємо вкладку Відгуки
                            tab_btn = page.locator('button[role="tab"]:has-text("Відгуки"), button[role="tab"]:has-text("Отзывы"), button[role="tab"]:has-text("Reviews")')
                            if await tab_btn.count() > 0:
                                await tab_btn.first.click()
                                await asyncio.sleep(1.5)

# 2. ПРИМУСОВЕ СОРТУВАННЯ (ОНОВЛЕНО ПО СКРІНШОТАХ)
                                try:
                                    # Шукаємо точну фразу "Найбільш релевантні" або "Самые релевантные"
                                    sort_btn = page.locator('button:has-text("Найбільш релевантні"), button:has-text("Самые релевантные")')

                                    # Гугл часто ховає це у div замість button
                                    if await sort_btn.count() == 0:
                                        sort_btn = page.locator('div[role="button"]:has-text("Найбільш релевантні"), div[role="button"]:has-text("Самые релевантные"), div[aria-label*="Сортувати"]')

                                    if await sort_btn.count() > 0:
                                        await sort_btn.first.click(force=True)
                                        await asyncio.sleep(1) # Даємо час менюшці випасти

                                        # Шукаємо пункт "Найновіші" або "Сначала новые"
                                        newest_btn = page.locator('text="Найновіші", text="Сначала новые", text="Спочатку нові"')

                                        if await newest_btn.count() > 0:
                                            await newest_btn.last.click(force=True)
                                            await asyncio.sleep(2.5) # Чекаємо завантаження нових відгуків
                                        else:
                                            # ЗАПАСНИЙ ПЛАН: якщо текст змінили, просто клікаємо на другий пункт у меню
                                            menu_items = await page.locator('div[role="menuitemradio"]').all()
                                            if len(menu_items) >= 2:
                                                await menu_items[1].click(force=True)
                                                await asyncio.sleep(2.5)
                                    else:
                                        print(f"   ⚠️ Не знайшов кнопку сортування для {name}")
                                except Exception as e:
                                    print(f"   ❌ Помилка при сортуванні: {e}")

                                # 3. РОЗГОРТАЄМО ТЕКСТ (Додано "Більше")
                                more_btns = await page.locator('button:has-text("Більше"), button:has-text("Ще"), button:has-text("Ещё")').all()
                                for btn in more_btns[:10]:
                                    try:
                                        await btn.click(timeout=1000)
                                        await asyncio.sleep(0.2)
                                    except: pass
                        except: pass

                        # 4. ПАРСИНГ ТА ФІЛЬТРАЦІЯ
                        review_blocks = await page.locator('div[data-review-id]').all()
                        for block in review_blocks:
                            if len(review_texts) >= 5: break

                            full_text = await block.inner_text()
                            if not full_text: continue

                            original_text = full_text
                            txt_lower = full_text.lower()

                            # Фільтри дати
                            if re.search(r'\b(год назад|года|лет|рік|роки|років)\b', txt_lower): continue
                            month_match = re.search(r'(\d+)\s+(месяц|місяц)', txt_lower)
                            if month_match and int(month_match.group(1)) > 3: continue

                            # Відрізаємо відповідь власника
                            for split_phrase in ["Ответ владельца", "Відповідь власника", "Response from the owner"]:
                                if split_phrase in original_text:
                                    original_text = original_text.split(split_phrase)[0]
                                    break

                            # Базове чищення від іконок Гугла та зайвих слів
                            clean_txt = original_text.replace('\n', ' ').replace('', '').replace('', '').replace('', '').replace('', '').replace('Нравится', '').replace('Поделиться', '').replace('Подобається', '').replace('Поділитися', '').replace('Більше', '').replace('Ещё', '').replace('Ще', '').replace('Посмотреть перевод (русский)', '').replace('Переглянути переклад (російська)', '').strip()

                            # МАГІЯ: Витягуємо тільки текст після слів "тому" або "назад" та слова "НОВИЙ"
                            match = re.search(r'(тому|назад)\s*(НОВИЙ)?\s*(.*)', clean_txt, re.IGNORECASE)
                            if match:
                                clean_txt = match.group(3).strip()

                            # Перевірка на дублікати (порівнюємо перші 30 символів)
                            signature = clean_txt[:30]

                            if len(clean_txt) > 10 and signature not in seen_reviews:
                                seen_reviews.add(signature)
                                review_texts.append(clean_txt)

                        full_reviews_text = " ||| ".join(review_texts) if review_texts else "Немає відгуків за останні 3 місяці"

                        if index % 5 == 0 or index == total:
                            print(f"⏳ Оброблено {index}/{total}...")

                        all_leads.append({
                            "name": name,
                            "address": address,
                            "phone": phone,
                            "website": website,
                            "place_url": url,
                            "reviews_text": full_reviews_text
                        })
                    except Exception as e:
                        print(f"Помилка з об'єктом {name}: {e}")
                        continue

            await browser.close()
        return all_leads