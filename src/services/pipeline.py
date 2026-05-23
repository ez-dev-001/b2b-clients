"""
Pipeline stages — shared logic for CMS detection and AI scoring.
=================================================================
Used by both `app.py` (Streamlit UI) and `run_scraper.py` (CLI).
Each function operates on a list[dict] and returns a new list[dict].
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

from src.services.cms_detector import check_cms
from src.services.ai_processor import AIProcessor
from src.services.language_detector import determine_lead_language
from src.db.repository import save_leads_to_db


# ── DB helper ─────────────────────────────────────────────────────────────────

async def save_leads(leads: list[dict]) -> None:
    """Persist leads to PostgreSQL (upsert). Uses a fresh session to avoid pool conflicts."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    # Create isolated engine to avoid "another operation is in progress"
    iso_engine = create_async_engine(
        "postgresql+asyncpg://postgres:postgres@localhost:5433/gmaps_scraper",
        echo=False,
    )
    iso_session = async_sessionmaker(iso_engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with iso_session() as session:
            await save_leads_to_db(session, leads)
    finally:
        await iso_engine.dispose()


# ── Stage 2: CMS Detection ───────────────────────────────────────────────────

def run_cms_stage(
    leads: list[dict],
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> list[dict]:
    """
    Detect CMS for every lead and return enriched copies.

    Args:
        leads: raw lead dicts from scraper.
        on_progress: optional callback(current, total, message) for UI updates.
    """
    enriched: list[dict] = []
    total = len(leads)

    for i, lead in enumerate(leads, 1):
        url = lead.get("website")
        name = lead.get("name", "?")

        cms = check_cms(url) if url else "No Website"
        lead_copy = dict(lead)
        lead_copy["cms_type"] = cms

        enriched.append(lead_copy)

        msg = f"[{i}/{total}] {name} → CMS: {cms}"
        if on_progress:
            on_progress(i, total, msg)

    return enriched


# ── Stage 3: AI Scoring ──────────────────────────────────────────────────────

async def _score_one(
    ai: AIProcessor,
    lead: dict,
) -> dict:
    """Score a single lead with AI, return an updated copy."""
    lead_copy = dict(lead)
    name = lead.get("name", "?")

    try:
        analysis = await ai.analyze_lead_data(
            name=name,
            website=lead.get("website"),
            cms_type=lead.get("cms_type"),
            reviews=lead.get("reviews_text", ""),
        )
        lead_copy["clean_name"] = analysis.get("clean_name", name)
        lead_copy["lead_score"] = analysis.get("lead_score", 0)
        lead_copy["ai_summary"] = analysis.get("ai_summary", "")
        lead_copy["reasoning"] = analysis.get("reasoning", "")
    except Exception as e:
        lead_copy["clean_name"] = name
        lead_copy["lead_score"] = 0
        lead_copy["ai_summary"] = f"Error: {e}"

    return lead_copy


def run_ai_stage(
    leads: list[dict],
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    _run_async: Optional[Callable] = None,
) -> tuple[list[dict], bool]:
    """
    Score every lead with GPT-4o-mini and return scored copies.

    Args:
        leads: enriched lead dicts (must have cms_type).
        on_progress: optional callback(current, total, message) for UI updates.
        _run_async: function to run a coroutine synchronously (needed in Streamlit).

    Returns:
        (scored_leads, ai_enabled) — ai_enabled is False if API key is missing.
    """
    # Default async runner
    if _run_async is None:
        _run_async = asyncio.run

    try:
        ai = AIProcessor()
        ai_enabled = True
    except ValueError:
        ai_enabled = False
        return list(leads), ai_enabled  # return originals untouched

    scored: list[dict] = []
    total = len(leads)

    for i, lead in enumerate(leads, 1):
        name = lead.get("name", "?")

        result = _run_async(_score_one(ai, lead))
        scored.append(result)

        score = result.get("lead_score", "?")
        msg = f"[{i}/{total}] {name} → 🤖 Score: {score}/10"
        if on_progress:
            on_progress(i, total, msg)

    return scored, ai_enabled


# ── Stage 4: Cold Intro Generation ───────────────────────────────────────────

async def _generate_one_intro(ai: AIProcessor, lead: dict) -> dict:
    """Generate a cold intro for a single lead, return updated copy."""
    lead_copy = dict(lead)

    # Detect language from website or city/query
    city_hint = lead.get("query") or lead.get("address") or ""
    language = determine_lead_language(
        website_url=lead.get("website"),
        city=city_hint,
    )
    lead_copy["lead_language"] = language

    intro = await ai.generate_cold_intro(
        clean_name=lead.get("clean_name") or lead.get("name", ""),
        cms_type=lead.get("cms_type", ""),
        reviews=lead.get("reviews_text", ""),
        ai_summary=lead.get("ai_summary", ""),
        rating=lead.get("rating"),
        reviews_count=lead.get("reviews_count"),
        category=lead.get("category"),
        language=language,
    )
    lead_copy["cold_intro"] = intro
    return lead_copy


def run_cold_intro_stage(
    leads: list[dict],
    *,
    min_score: int = 7,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    _run_async: Optional[Callable] = None,
) -> tuple[list[dict], bool]:
    """
    Generate cold email first-line for leads with score >= min_score.

    Args:
        leads: scored lead dicts (must have lead_score).
        min_score: threshold for cold intro generation.
        on_progress: optional callback(current, total, message).
        _run_async: function to run a coroutine synchronously.

    Returns:
        (all_leads_updated, ai_enabled)
    """
    if _run_async is None:
        _run_async = asyncio.run

    try:
        ai = AIProcessor()
        ai_enabled = True
    except ValueError:
        return list(leads), False

    # Split: leads that qualify vs those that don't
    result: list[dict] = []
    qualifying = [l for l in leads if (l.get("lead_score") or 0) >= min_score]
    total = len(qualifying)

    if total == 0:
        if on_progress:
            on_progress(0, 0, "⚠️ Немає лідів з score ≥ " + str(min_score))
        return list(leads), ai_enabled

    # Index for progress
    qi = 0
    for lead in leads:
        score = lead.get("lead_score") or 0
        if score >= min_score:
            qi += 1
            updated = _run_async(_generate_one_intro(ai, lead))
            result.append(updated)
            name = lead.get("clean_name") or lead.get("name", "?")
            msg = f"[{qi}/{total}] {name} → ✉️ Готово"
            if on_progress:
                on_progress(qi, total, msg)
        else:
            result.append(dict(lead))  # pass through unchanged

    return result, ai_enabled


# ── Stage 5: Email Finder ────────────────────────────────────────────────────

def run_email_finder_stage(
    leads: list[dict],
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    _run_async: Optional[Callable] = None,
) -> list[dict]:
    """
    Find emails via waterfall: Google Maps → mailto → site crawl.

    Returns updated lead dicts with `email` and `email_source` fields.
    """
    from src.services.email_finder import find_email

    result: list[dict] = []
    total = len(leads)

    for i, lead in enumerate(leads, 1):
        lead_copy = dict(lead)
        name = lead.get("clean_name") or lead.get("name", "?")

        try:
            email, source, socials = find_email(lead)
            lead_copy["email"] = email
            lead_copy["email_source"] = source
            # Merge social media links
            for key in ("instagram", "facebook", "telegram", "tiktok"):
                if socials.get(key):
                    lead_copy[key] = socials[key]
            icon = "✅" if email else "—"
            src_label = f" ({source})" if source else ""
            socials_found = [k for k in ("instagram", "facebook", "telegram", "tiktok") if socials.get(k)]
            socials_label = f" 📱 {', '.join(socials_found)}" if socials_found else ""
            msg = f"[{i}/{total}] {name} → {icon} {email or 'не знайдено'}{src_label}{socials_label}"
        except Exception as e:
            lead_copy["email"] = None
            lead_copy["email_source"] = None
            msg = f"[{i}/{total}] {name} → ⚠️ {e}"

        result.append(lead_copy)
        if on_progress:
            on_progress(i, total, msg)

    # Save to DB via the provided _run_async (persistent background loop)
    if _run_async is None:
        _run_async = asyncio.run
    try:
        _run_async(save_leads(result))
    except Exception:
        pass  # DB save failure doesn't block returning results

    return result
