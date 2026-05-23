# 🗺️ Google Maps Scraper & Lead Generation

A production-ready web scraping and lead generation tool built with Python 3.12, Playwright, OpenAI, SQLAlchemy (Async), PostgreSQL, and a **Streamlit UI**.

## ✨ Features

### Four-Stage AI Pipeline

| Stage | Name | Description |
|---|---|---|
| **1** | 🔍 Збір точок | Scrolls Google Maps, collects names, addresses, phones, websites, reviews |
| **2** | 🌐 CMS Детекція | Detects CMS/builder (Tilda, Wix, WordPress, etc.) for each website |
| **3** | 🤖 AI Аналіз | GPT-4o scores each lead (0–100) with a summary and recommendations |
| **4** | ✉️ Cold Intro | Generates a personalized ice-breaker email in the lead's detected language |

### Smart Features

- **🔄 Auto-Run Mode** — Toggle in sidebar to chain all 4 stages automatically with one click.
- **🌍 Geolocation Override** — Scraper "teleports" the browser to the target city, so you get London results even from Bangkok.
- **🗣️ Language Detection** — Checks `<html lang="...">` on the lead's website, falls back to city mapping. Supports 20+ languages.
- **🎯 Score Threshold** — Sidebar slider filters leads by AI score before generating cold intros (Stage 4).
- **📊 Export** — Download results as `.xlsx` or `.csv` with all fields.
- **🔎 Live Search** — Filter across all fields in the results table.
- **🤫 Stealth Mode** — Playwright with anti-detection (spoofed `webdriver`, `plugins`, `languages`).

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Package manager | Poetry |
| UI | Streamlit |
| Scraping | Playwright (async) |
| Database | PostgreSQL 17 (Docker) |
| ORM | SQLAlchemy 2.0 + asyncpg |
| Migrations | Alembic |
| AI | OpenAI GPT-4o |
| CMS Detection | requests + BeautifulSoup |

## 🚀 Getting Started

### 1. Install dependencies
```bash
poetry install
poetry run playwright install chromium
```

### 2. Start the database
```bash
docker-compose up -d
```
- PostgreSQL: `localhost:5433`
- Adminer UI: `http://localhost:8080`

### 3. Configure environment
```bash
cp .env.example .env
```
Edit `.env`:
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/gmaps_scraper
OPENAI_API_KEY=sk-...  # Required for Stages 3 & 4
```

### 4. Run migrations
```bash
poetry run alembic upgrade head
```

### 5. Launch the UI
```bash
poetry run streamlit run app.py
```
Open `http://localhost:8501` in your browser.

### 6. (Optional) Run from CLI
```bash
poetry run python src/services/run_scraper.py
```

## 🎮 UI Workflow

### Manual Mode (default)
1. Enter search queries in the sidebar (one per line, e.g. `Flower shop London`).
2. Set the **lead limit** with the slider (default: 50).
3. Click **"🚀 Запустити збір"** → Stage 1 collects leads from Google Maps.
4. Click **"🌐 CMS Детекція"** → Stage 2 checks each website's CMS.
5. Click **"🤖 AI Аналіз"** → Stage 3 scores leads with GPT-4o.
6. Set the **min score threshold** slider → Click **"✉️ Cold Intro"** → Stage 4 generates personalized emails.
7. Browse, filter, and **download** results.

### Auto Mode
1. Enable **"🔄 Авто-режим (1→4)"** toggle in the sidebar.
2. Click **"🚀 Повний аналіз (1→4)"** → All 4 stages run sequentially.

## 🌍 Geolocation & Language

The scraper embeds target city coordinates directly into the Google Maps URL, so results are always location-accurate regardless of your physical location.

**Supported cities (30+):** Kyiv, Lviv, Odesa, Kharkiv, Dnipro, Warsaw, Krakow, Wroclaw, Gdansk, London, Manchester, Berlin, Munich, Hamburg, Prague, Paris, Amsterdam, Rome, Madrid, Barcelona, Vienna, Bangkok, Istanbul, New York, Los Angeles, and more.

**Language detection priority:**
1. **Website** — Fetches `<html lang="uk">` → "Ukrainian"
2. **City mapping** — Falls back to the city in the search query
3. **Default** — "English"

Cold intros are generated in the detected language with native-sounding examples.

## 📁 Project Structure

```text
.
├── app.py                          # Streamlit UI (4-stage control panel)
├── src/
│   ├── core/                       # Config (pydantic-settings) & DB engine
│   ├── models/                     # SQLAlchemy models (Lead)
│   ├── services/
│   │   ├── scraper.py              # Google Maps scraper (Stage 1)
│   │   ├── cms_detector.py         # CMS detection (Stage 2)
│   │   ├── ai_processor.py         # AI scoring & cold intro (Stages 3-4)
│   │   ├── language_detector.py    # Website/city language detection
│   │   ├── pipeline.py             # Pipeline orchestration & DB save
│   │   └── run_scraper.py          # CLI entry point
│   ├── scraper/
│   │   └── google_maps.py          # Alternative scraper (Google Search Local)
│   └── db/
│       ├── database.py             # Async engine & session
│       ├── repository.py           # DB write logic (upsert)
│       └── migrations/             # Alembic migration scripts
├── tests/
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

## 📝 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `OPENAI_API_KEY` | ✅ (Stages 3-4) | OpenAI API key for AI scoring & cold intros |
