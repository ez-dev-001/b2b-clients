"""
Streamlit UI — Google Maps Lead Scraper
========================================
Three-stage pipeline:
  Stage 1 → Collect raw business points via GoogleMapsScraper
  Stage 2 → CMS detection + save to DB
  Stage 3 → AI scoring (GPT-4o-mini) + save to DB

Run:
    poetry run streamlit run app.py
"""

import asyncio
import io
import sys
import threading
import queue
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

# ── project root on path ─────────────────────────────────────────────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.scraper import GoogleMapsScraper
from src.services.pipeline import run_cms_stage, run_ai_stage, run_cold_intro_stage, run_email_finder_stage, save_leads

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Google Maps Lead Scraper",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Dark premium palette */
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
        color: #e6edf3;
    }
    [data-testid="stSidebar"] {
        background: #161b22;
        border-right: 1px solid #30363d;
    }
    [data-testid="stSidebar"] .block-container { padding-top: 2rem; }

    /* Metric cards */
    [data-testid="metric-container"] {
        background: #21262d;
        border: 1px solid #30363d;
        border-radius: 12px;
        padding: 1rem 1.25rem;
    }

    /* Buttons */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
        border: none;
    }
    .stButton > button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.4); }

    /* Stage cards */
    .stage-card {
        background: #21262d;
        border: 1px solid #30363d;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
    }
    .stage-badge {
        display: inline-block;
        padding: 3px 12px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        margin-bottom: 0.5rem;
    }
    .badge-1 { background: #1f6feb30; color: #58a6ff; border: 1px solid #1f6feb; }
    .badge-2 { background: #1a7f3720; color: #56d364; border: 1px solid #2ea043; }
    .badge-done { background: #2ea04320; color: #56d364; border: 1px solid #2ea043; }
    .badge-waiting { background: #30363d; color: #8b949e; border: 1px solid #484f58; }

    /* Log box */
    .log-box {
        background: #0d1117;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 1rem;
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        font-size: 0.78rem;
        max-height: 260px;
        overflow-y: auto;
        white-space: pre-wrap;
        color: #8b949e;
    }

    /* Divider */
    hr { border-color: #30363d; }

    /* Table */
    .dataframe { border: 1px solid #30363d !important; }
    .dataframe td, .dataframe th {
        background: #161b22 !important;
        color: #e6edf3 !important;
        border-color: #30363d !important;
    }
</style>
""", unsafe_allow_html=True)


# ── Session-state helpers ─────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "stage1_done": False,
        "stage2_done": False,
        "stage3_done": False,
        "stage4_done": False,
        "stage5_done": False,
        "raw_leads": [],      # list[dict] from scraper
        "enriched_leads": [], # list[dict] after CMS enrichment
        "scored_leads": [],   # list[dict] after AI scoring
        "intro_leads": [],    # list[dict] after cold intro generation
        "email_leads": [],    # list[dict] after email finder
        "stage1_log": "",
        "stage2_log": "",
        "stage3_log": "",
        "stage4_log": "",
        "stage5_log": "",
        "running": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── Async helpers ─────────────────────────────────────────────────────────────

# Persistent event loop in a background thread — avoids "Event loop is closed"
# errors from OpenAI's AsyncClient / httpx when asyncio.run() destroys the loop.
# Added specifically for Windows so Playwright can launch subprocesses
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

_BG_LOOP: asyncio.AbstractEventLoop = asyncio.new_event_loop()

def _start_bg_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

_BG_THREAD = threading.Thread(target=_start_bg_loop, args=(_BG_LOOP,), daemon=True)
_BG_THREAD.start()


def _run_async(coro):
    """Run an async coroutine on the persistent background event loop."""
    future = asyncio.run_coroutine_threadsafe(coro, _BG_LOOP)
    return future.result()  # blocks until done


class StreamlitLogHandler:
    """Redirect Python logging to a Streamlit placeholder."""

    def __init__(self, placeholder, key: str):
        self._placeholder = placeholder
        self._key = key

    def emit(self, message: str):
        st.session_state[self._key] += message + "\n"
        self._placeholder.markdown(
            f'<div class="log-box">{st.session_state[self._key]}</div>',
            unsafe_allow_html=True,
        )


# ── Stage 1: Scrape raw leads ─────────────────────────────────────────────────

async def _stage1_scrape(queries: list[str], headless: bool, max_results: int = 500) -> list[dict]:
    scraper = GoogleMapsScraper(headless=headless)
    leads = await scraper.scrape_queries(queries, max_results=max_results)
    return leads


def run_stage1(queries: list[str], headless: bool, max_leads: int = 500):
    """Execute Stage 1 and update session state."""
    st.session_state["stage1_log"] = ""
    st.session_state["stage1_done"] = False
    st.session_state["stage2_done"] = False
    st.session_state["stage3_done"] = False
    st.session_state["stage4_done"] = False
    st.session_state["raw_leads"] = []
    st.session_state["enriched_leads"] = []
    st.session_state["scored_leads"] = []
    st.session_state["intro_leads"] = []

    leads = _run_async(_stage1_scrape(queries, headless, max_results=max_leads))
    st.session_state["raw_leads"] = leads
    st.session_state["stage1_done"] = True
    return leads


# ── Stage 2: CMS Detection ───────────────────────────────────────────────────

def run_stage2(leads: list[dict], log_placeholder):
    """Execute Stage 2: CMS detection + DB save (delegates to pipeline)."""
    st.session_state["stage2_log"] = ""
    st.session_state["stage3_done"] = False
    st.session_state["scored_leads"] = []
    progress = log_placeholder.progress(0)

    def on_progress(current, total, msg):
        st.session_state["stage2_log"] += msg + "\n"
        progress.progress(current / total)

    enriched = run_cms_stage(leads, on_progress=on_progress)

    # Save to DB
    try:
        _run_async(save_leads(enriched))
        st.session_state["stage2_log"] += "\n✅ Збережено в PostgreSQL."
    except Exception as e:
        st.session_state["stage2_log"] += f"\n⚠️ DB save failed: {e}"

    st.session_state["enriched_leads"] = enriched
    st.session_state["stage2_done"] = True
    return enriched


# ── Stage 3: AI Scoring ───────────────────────────────────────────────────────

def run_stage3(leads: list[dict], log_placeholder):
    """Execute Stage 3: AI scoring + DB save (delegates to pipeline)."""
    st.session_state["stage3_log"] = ""
    progress = log_placeholder.progress(0)

    def on_progress(current, total, msg):
        st.session_state["stage3_log"] += msg + "\n"
        progress.progress(current / total)

    scored, ai_enabled = run_ai_stage(
        leads, on_progress=on_progress, _run_async=_run_async
    )

    if not ai_enabled:
        st.session_state["stage3_log"] += "⚠️ AI вимкнено: OPENAI_API_KEY не знайдено\n"

    # Save to DB
    if ai_enabled:
        try:
            _run_async(save_leads(scored))
            st.session_state["stage3_log"] += "\n✅ Збережено в PostgreSQL."
        except Exception as e:
            st.session_state["stage3_log"] += f"\n⚠️ DB save failed: {e}"

    st.session_state["scored_leads"] = scored
    st.session_state["stage3_done"] = True
    return scored


# ── Stage 4: Cold Intro ───────────────────────────────────────────────────────

def run_stage4(leads: list[dict], min_score: int, log_placeholder):
    """Генерує перше речення холодного листа для лідів зі score >= min_score."""
    st.session_state["stage4_log"] = ""
    progress = log_placeholder.progress(0)

    def on_progress(current, total, msg):
        st.session_state["stage4_log"] += msg + "\n"
        if total > 0:
            progress.progress(current / total)

    result, ai_enabled = run_cold_intro_stage(
        leads, min_score=min_score,
        on_progress=on_progress, _run_async=_run_async,
    )

    if not ai_enabled:
        st.session_state["stage4_log"] += "⚠️ AI вимкнено\n"

    # Save to DB
    if ai_enabled:
        try:
            _run_async(save_leads(result))
            st.session_state["stage4_log"] += "\n✅ Збережено в PostgreSQL."
        except Exception as e:
            st.session_state["stage4_log"] += f"\n⚠️ DB save failed: {e}"

    st.session_state["intro_leads"] = result
    st.session_state["stage4_done"] = True
    return result


# ── Stage 5: Email Finder ─────────────────────────────────────────────────────

def run_stage5(leads: list[dict], log_placeholder):
    """Знаходить email через waterfall: GMaps → mailto → site crawl."""
    st.session_state["stage5_log"] = ""
    progress = log_placeholder.progress(0)

    def on_progress(current, total, msg):
        st.session_state["stage5_log"] += msg + "\n"
        if total > 0:
            progress.progress(current / total)

    result = run_email_finder_stage(leads, on_progress=on_progress, _run_async=_run_async)

    st.session_state["email_leads"] = result
    st.session_state["stage5_done"] = True
    return result


# ── Export helpers ────────────────────────────────────────────────────────────

def _leads_to_excel(leads: list[dict]) -> bytes:
    df = pd.DataFrame(leads)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
        worksheet = writer.sheets["Leads"]
        # Auto-fit columns
        for i, col in enumerate(df.columns):
            max_len = max(df[col].astype(str).map(len).max(), len(col)) + 4
            worksheet.set_column(i, i, min(max_len, 60))
    return buf.getvalue()


def _leads_to_csv(leads: list[dict]) -> bytes:
    df = pd.DataFrame(leads)
    return df.to_csv(index=False).encode("utf-8-sig")


# ── UI Layout ─────────────────────────────────────────────────────────────────

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<h1 style='text-align:center; font-size:2.2rem; font-weight:800;
           background: linear-gradient(90deg,#58a6ff,#56d364);
           -webkit-background-clip:text; -webkit-text-fill-color:transparent;
           margin-bottom:0.25rem;'>
  🗺️ Google Maps Lead Scraper
</h1>
<p style='text-align:center; color:#8b949e; margin-top:0; margin-bottom:2rem;'>
  Чотириетапний збір та обробка лідів
</p>
<hr>
""", unsafe_allow_html=True)

# ── Sidebar: configuration ─────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Конфігурація")
    headless_mode = st.toggle("Headless режим", value=False,
                              help="Запустити браузер без вікна (у фоні)")
    auto_run = st.toggle("🔄 Авто-режим (1→4)", value=False,
                         help="Всі 4 етапи виконуються послідовно після натискання кнопки у Кроці 1.")
    st.divider()
    st.markdown("### 📋 Запити")
    raw_queries_input = st.text_area(
        "Один запит — один рядок",
        value="Flower shop Kyiv\nBeauty salon Lviv",
        height=180,
        placeholder="Flower shop Kyiv\nBarber Warsaw\n...",
    )
    queries: list[str] = [
        q.strip() for q in raw_queries_input.splitlines() if q.strip()
    ]
    st.info(f"**{len(queries)}** запит(ів) готові до виконання")

    st.divider()
    st.markdown("### 🎯 Ліміт лідів")
    max_leads = st.slider(
        "Максимум лідів (загалом)",
        min_value=10,
        max_value=500,
        value=50,
        step=10,
        help="Скільки лідів зберегти після збору. Скрапер зупиниться раніше якщо результатів менше.",
    )

    st.divider()
    st.markdown("### ✉️ Cold Intro")
    min_score_threshold = st.slider(
        "Мінімальний score для листа",
        min_value=1,
        max_value=10,
        value=7,
        step=1,
        help="Генерувати перше речення листа тільки для лідів з оцінкою ≥ цього порогу.",
    )

    st.divider()

    # Status summary
    s1 = st.session_state
    st.markdown("### 📊 Статус")
    col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
    col_s1.metric("Зібрано", len(s1["raw_leads"]))
    col_s2.metric("CMS", len(s1["enriched_leads"]))
    col_s3.metric("AI", len(s1["scored_leads"]))
    col_s4.metric("✉️", len(s1["intro_leads"]))
    n_emails = sum(1 for l in s1["email_leads"] if l.get("email"))
    col_s5.metric("📧", n_emails)


# ── Main content area: Row 1 (Stages 1 & 2) ─────────────────────────────────────
col_sc1, col_sc2 = st.columns(2, gap="medium")

# ── Stage 1 ──────────────────────────────────────────────────────────────────
with col_sc1:
    badge1_class = "badge-done" if st.session_state["stage1_done"] else "badge-1"
    badge1_text = "✅ ВИКОНАНО" if st.session_state["stage1_done"] else "КРОК 1"
    st.markdown(f"""
    <div class="stage-card">
      <span class="stage-badge {badge1_class}">{badge1_text}</span>
      <h3 style='margin:0.25rem 0 0.75rem;'>Збір точок</h3>
      <p style='color:#8b949e; font-size:0.88rem; margin:0;'>
        Scraper відкриває Google Maps, прокручує результати і збирає
        базову інформацію: назву, адресу, телефон, сайт, посилання.
      </p>
    </div>
    """, unsafe_allow_html=True)

    log1_placeholder = st.empty()

    btn1_label = "🚀 Повний аналіз (1→5)" if auto_run else "🚀 Запустити збір"
    btn1_disabled = st.session_state.get("running", False)
    if st.button(btn1_label, width="stretch",
                 type="primary", disabled=btn1_disabled):
        if not queries:
            st.warning("Введіть хоча б один запит у бічній панелі.")
        else:
            st.session_state["running"] = True

            # Stage 1: Scrape
            with st.spinner("Stage 1: збираємо точки з Google Maps…"):
                try:
                    leads = run_stage1(queries, headless=headless_mode, max_leads=max_leads)
                    st.success(f"✅ Зібрано **{len(leads)}** лідів (ліміт: {max_leads})!")
                except Exception as e:
                    st.error(f"❌ Помилка Stage 1: {e}")
                    st.session_state["running"] = False
                    st.rerun()

            if auto_run and st.session_state["stage1_done"]:
                # Stage 2: CMS
                with st.spinner("Stage 2: CMS детекція…"):
                    try:
                        run_stage2(st.session_state["raw_leads"], log1_placeholder)
                        st.success("✅ CMS визначено!")
                    except Exception as e:
                        st.error(f"❌ Помилка Stage 2: {e}")

                # Stage 3: AI
                if st.session_state["stage2_done"]:
                    with st.spinner("Stage 3: AI аналіз…"):
                        try:
                            run_stage3(st.session_state["enriched_leads"], log1_placeholder)
                            st.success("✅ AI скорінг завершено!")
                        except Exception as e:
                            st.error(f"❌ Помилка Stage 3: {e}")

                # Stage 4: Cold Intro
                if st.session_state["stage3_done"]:
                    with st.spinner("Stage 4: генерація cold intro…"):
                        try:
                            result = run_stage4(
                                st.session_state["scored_leads"],
                                min_score_threshold,
                                log1_placeholder,
                            )
                            n_intros = sum(1 for l in result if l.get("cold_intro"))
                            st.success(f"✅ Згенеровано **{n_intros}** листів!")
                        except Exception as e:
                            st.error(f"❌ Помилка Stage 4: {e}")

                # Stage 5: Email Finder
                if st.session_state["stage4_done"]:
                    with st.spinner("Stage 5: пошук email…"):
                        try:
                            result5 = run_stage5(
                                st.session_state["intro_leads"],
                                log1_placeholder,
                            )
                            n_emails = sum(1 for l in result5 if l.get("email"))
                            st.success(f"✅ Знайдено **{n_emails}** email!")
                        except Exception as e:
                            st.error(f"❌ Помилка Stage 5: {e}")

            st.session_state["running"] = False
            st.rerun()

    # Show raw results preview
    if st.session_state["stage1_done"] and st.session_state["raw_leads"]:
        st.markdown("**Попередній перегляд (raw):**")
        raw_df = pd.DataFrame(st.session_state["raw_leads"])
        st.dataframe(raw_df, width="stretch", height=220)


# ── Stage 2 ──────────────────────────────────────────────────────────────────
with col_sc2:
    s2_ready = st.session_state["stage1_done"] and bool(st.session_state["raw_leads"])
    badge2_class = "badge-done" if st.session_state["stage2_done"] else ("badge-2" if s2_ready else "badge-waiting")
    badge2_text = "✅ ВИКОНАНО" if st.session_state["stage2_done"] else ("КРОК 2" if s2_ready else "ОЧІКУВАННЯ")
    st.markdown(f"""
    <div class="stage-card">
      <span class="stage-badge {badge2_class}">{badge2_text}</span>
      <h3 style='margin:0.25rem 0 0.75rem;'>CMS Детекція</h3>
      <p style='color:#8b949e; font-size:0.88rem; margin:0;'>
        15+ CMS & Builders. Соцмережі розпізнаються без запитів.
        Автозбереження в БД.
      </p>
    </div>
    """, unsafe_allow_html=True)

    log2_placeholder = st.empty()

    btn2_disabled = not s2_ready or st.session_state.get("running", False)
    if st.button("⚙️ Обробка CMS", width="stretch",
                 type="secondary", disabled=btn2_disabled):
        st.session_state["running"] = True
        with st.spinner("Stage 2: Перевірка сайтів…"):
            try:
                enriched = run_stage2(
                    st.session_state["raw_leads"],
                    log2_placeholder,
                )
                st.success(f"✅ CMS визначено для **{len(enriched)}** лідів!")
            except Exception as e:
                st.error(f"❌ Помилка: {e}")
        st.session_state["running"] = False
        st.rerun()

    if st.session_state["stage2_log"]:
        st.markdown(
            f'<div class="log-box">{st.session_state["stage2_log"]}</div>',
            unsafe_allow_html=True,
        )

# ── Main content area: Row 2 (Stages 3 & 4) ─────────────────────────────────────
col_sc3, col_sc4 = st.columns(2, gap="medium")

# ── Stage 3 ──────────────────────────────────────────────────────────────────
with col_sc3:
    s3_ready = st.session_state["stage2_done"] and bool(st.session_state["enriched_leads"])
    badge3_class = "badge-done" if st.session_state["stage3_done"] else ("badge-2" if s3_ready else "badge-waiting")
    badge3_text = "✅ ВИКОНАНО" if st.session_state["stage3_done"] else ("КРОК 3" if s3_ready else "ОЧІКУВАННЯ")
    st.markdown(f"""
    <div class="stage-card">
      <span class="stage-badge {badge3_class}">{badge3_text}</span>
      <h3 style='margin:0.25rem 0 0.75rem;'>AI Аналіз</h3>
      <p style='color:#8b949e; font-size:0.88rem; margin:0;'>
        GPT-4o-mini оцінює ліда (0-10) на основі сайту, CMS та відгуків.
      </p>
    </div>
    """, unsafe_allow_html=True)

    log3_placeholder = st.empty()

    btn3_disabled = not s3_ready or st.session_state.get("running", False)
    if st.button("🤖 AI Скорінг", width="stretch",
                 type="secondary", disabled=btn3_disabled):
        st.session_state["running"] = True
        with st.spinner("Stage 3: AI аналіз…"):
            try:
                scored = run_stage3(
                    st.session_state["enriched_leads"],
                    log3_placeholder,
                )
                st.success(f"✅ AI оцінив **{len(scored)}** лідів!")
            except Exception as e:
                st.error(f"❌ Помилка: {e}")
        st.session_state["running"] = False
        st.rerun()

    if st.session_state["stage3_log"]:
        st.markdown(
            f'<div class="log-box">{st.session_state["stage3_log"]}</div>',
            unsafe_allow_html=True,
        )

# ── Stage 4 ──────────────────────────────────────────────────────────────────
with col_sc4:
    s4_ready = st.session_state["stage3_done"] and bool(st.session_state["scored_leads"])
    badge4_class = "badge-done" if st.session_state["stage4_done"] else ("badge-2" if s4_ready else "badge-waiting")
    badge4_text = "✅ ВИКОНАНО" if st.session_state["stage4_done"] else ("КРОК 4" if s4_ready else "ОЧІКУВАННЯ")
    st.markdown(f"""
    <div class="stage-card">
      <span class="stage-badge {badge4_class}">{badge4_text}</span>
      <h3 style='margin:0.25rem 0 0.75rem;'>✉️ Cold Intro</h3>
      <p style='color:#8b949e; font-size:0.88rem; margin:0;'>
        Генерує перше речення листа для лідів зі score ≥ {min_score_threshold}.
      </p>
    </div>
    """, unsafe_allow_html=True)

    log4_placeholder = st.empty()

    btn4_disabled = not s4_ready or st.session_state.get("running", False)
    if st.button("✉️ Генерувати листи", width="stretch",
                 type="secondary", disabled=btn4_disabled):
        st.session_state["running"] = True
        with st.spinner("Stage 4: генерація cold intro…"):
            try:
                result = run_stage4(
                    st.session_state["scored_leads"],
                    min_score_threshold,
                    log4_placeholder,
                )
                n_intros = sum(1 for l in result if l.get("cold_intro"))
                st.success(f"✅ Згенеровано **{n_intros}** листів!")
            except Exception as e:
                st.error(f"❌ Помилка: {e}")
        st.session_state["running"] = False
        st.rerun()

    if st.session_state["stage4_log"]:
        st.markdown(
            f'<div class="log-box">{st.session_state["stage4_log"]}</div>',
            unsafe_allow_html=True,
        )


# ── Stage 5 card ─────────────────────────────────────────────────────────────
st.markdown("---")
col_sc5_left, col_sc5_right = st.columns([1, 2], gap="medium")

with col_sc5_left:
    s5_ready = st.session_state["stage4_done"] and bool(st.session_state["intro_leads"])
    badge5_class = "badge-done" if st.session_state["stage5_done"] else ("badge-2" if s5_ready else "badge-waiting")
    badge5_text = "✅ ВИКОНАНО" if st.session_state["stage5_done"] else ("КРОК 5" if s5_ready else "ОЧІКУВАННЯ")
    st.markdown(f"""
    <div class="stage-card">
      <span class="stage-badge {badge5_class}">{badge5_text}</span>
      <h3 style='margin:0.25rem 0 0.75rem;'>📧 Email Finder</h3>
      <p style='color:#8b949e; font-size:0.88rem; margin:0;'>
        Waterfall: Google Maps → mailto → crawl (contact, about pages).
      </p>
    </div>
    """, unsafe_allow_html=True)

    log5_placeholder = st.empty()

    btn5_disabled = not s5_ready or st.session_state.get("running", False)
    if st.button("📧 Знайти email", width="stretch",
                 type="secondary", disabled=btn5_disabled):
        st.session_state["running"] = True
        with st.spinner("Stage 5: пошук email…"):
            try:
                result5 = run_stage5(st.session_state["intro_leads"], log5_placeholder)
                n_emails = sum(1 for l in result5 if l.get("email"))
                st.success(f"✅ Знайдено **{n_emails}** email!")
            except Exception as e:
                st.error(f"❌ Помилка: {e}")
        st.session_state["running"] = False
        st.rerun()

    if st.session_state["stage5_log"]:
        st.markdown(
            f'<div class="log-box">{st.session_state["stage5_log"]}</div>',
            unsafe_allow_html=True,
        )

with col_sc5_right:
    # Show email results summary if available
    if st.session_state["stage5_done"] and st.session_state["email_leads"]:
        el = st.session_state["email_leads"]
        found = [l for l in el if l.get("email")]
        st.markdown(f"**Знайдено {len(found)}/{len(el)} email:**")
        if found:
            email_df = pd.DataFrame([{
                "name": l.get("clean_name") or l.get("name"),
                "email": l.get("email"),
                "source": l.get("email_source"),
                "instagram": l.get("instagram"),
                "facebook": l.get("facebook"),
                "telegram": l.get("telegram"),
                "website": l.get("website"),
            } for l in found])
            st.dataframe(email_df, width="stretch", height=220)


# ── Leads Table & Download ─────────────────────────────────────────────────────
st.divider()
st.markdown("## 📥 Ліди — фінальна таблиця")

# Determine which dataset to show: prefer email > intro > scored > enriched > raw
display_leads = (
    st.session_state["email_leads"]
    or st.session_state["intro_leads"]
    or st.session_state["scored_leads"]
    or st.session_state["enriched_leads"]
    or st.session_state["raw_leads"]
)

if not display_leads:
    st.info("Запустіть Крок 1, щоб побачити ліди тут.")
else:
    df = pd.DataFrame(display_leads)

    # Column reorder: put important cols first (covers both raw & enriched)
    priority_cols = [
        "lead_score", "clean_name", "email", "email_source",
        "instagram", "facebook", "telegram", "tiktok",
        "cold_intro", "ai_summary", "name", "phone", "website", "address",
        "category", "rating", "reviews_count",
        "reviews_text", "cms_type", "place_url", "query",
    ]
    ordered_cols = [c for c in priority_cols if c in df.columns] + \
                   [c for c in df.columns if c not in priority_cols]
    df = df[ordered_cols]

    # Search / filter
    search_term = st.text_input("🔍 Фільтр за назвою / телефоном / адресою", "")
    if search_term:
        mask = df.apply(
            lambda col: col.astype(str).str.contains(search_term, case=False, na=False)
        ).any(axis=1)
        df_view = df[mask]
    else:
        df_view = df

    col_info1, col_info2, col_info3 = st.columns(3)
    col_info1.metric("Всього лідів", len(df))
    col_info2.metric("Показано", len(df_view))
    col_info3.metric("Останнє оновлення", datetime.now().strftime("%H:%M:%S"))

    st.dataframe(df_view, width="stretch", height=420)

    # ── Download buttons ───────────────────────────────────────────────────────
    st.markdown("### ⬇️ Завантажити")
    dl_col1, dl_col2, _ = st.columns([1, 1, 2])

    with dl_col1:
        excel_bytes = _leads_to_excel(display_leads)
        st.download_button(
            label="📊 Excel (.xlsx)",
            data=excel_bytes,
            file_name=f"leads_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

    with dl_col2:
        csv_bytes = _leads_to_csv(display_leads)
        st.download_button(
            label="📄 CSV (.csv)",
            data=csv_bytes,
            file_name=f"leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            width="stretch",
        )
