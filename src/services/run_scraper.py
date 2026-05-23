"""
CLI script — four-stage lead pipeline.
========================================
Stage 1 → Scrape Google Maps
Stage 2 → CMS detection  (pipeline.run_cms_stage)
Stage 3 → AI scoring     (pipeline._score_one)
Stage 4 → Cold intro     (pipeline._generate_one_intro)

Run:
    poetry run python src/services/run_scraper.py
"""

import asyncio

from src.services.scraper import GoogleMapsScraper
from src.services.cms_detector import check_cms
from src.services.ai_processor import AIProcessor
from src.services.pipeline import run_cms_stage, save_leads


async def main():
    scraper = GoogleMapsScraper()
    queries = ["Flower shop Kyiv"]

    # ── Stage 1: Scrape ──────────────────────────────────────────────────────
    print("\n🔍 Stage 1: Збір даних...")
    raw_leads = await scraper.scrape_queries(queries, max_results=10)

    # ── Stage 2: CMS Detection ───────────────────────────────────────────────
    print("\n🔍 Stage 2: CMS Детекція...")
    enriched = run_cms_stage(
        raw_leads,
        on_progress=lambda cur, tot, msg: print(f"   {msg}"),
    )

    print("\n💾 Збереження після Stage 2...")
    await save_leads(enriched)

    # ── Stage 3: AI Scoring ──────────────────────────────────────────────────
    print("\n🤖 Stage 3: AI Аналіз...")
    try:
        ai = AIProcessor()
    except ValueError:
        print("   ⚠️ AI вимкнено: OPENAI_API_KEY не знайдено")
        return

    scored = []
    for i, lead in enumerate(enriched, 1):
        name = lead.get("name", "?")
        try:
            analysis = await ai.analyze_lead_data(
                name=name,
                website=lead.get("website"),
                cms_type=lead.get("cms_type"),
                reviews=lead.get("reviews_text", ""),
            )
            lead_copy = dict(lead)
            lead_copy["clean_name"] = analysis.get("clean_name", name)
            lead_copy["lead_score"] = analysis.get("lead_score", 0)
            lead_copy["ai_summary"] = analysis.get("ai_summary", "")
            lead_copy["reasoning"] = analysis.get("reasoning", "")
            scored.append(lead_copy)
            print(f"   [{i}/{len(enriched)}] {name} → 🤖 Score: {lead_copy['lead_score']}/10")
        except Exception as e:
            print(f"   [{i}/{len(enriched)}] {name} → ⚠️ Error: {e}")
            scored.append(dict(lead))

    print("\n💾 Збереження після Stage 3...")
    await save_leads(scored)

    # ── Stage 4: Cold Intro ──────────────────────────────────────────────────
    MIN_SCORE = 7
    qualifying = [l for l in scored if (l.get("lead_score") or 0) >= MIN_SCORE]
    print(f"\n✉️ Stage 4: Cold Intro ({len(qualifying)} лідів зі score ≥ {MIN_SCORE})...")

    result = []
    qi = 0
    for lead in scored:
        score = lead.get("lead_score") or 0
        if score >= MIN_SCORE:
            qi += 1
            name = lead.get("clean_name") or lead.get("name", "?")
            intro = await ai.generate_cold_intro(
                clean_name=name,
                cms_type=lead.get("cms_type", ""),
                reviews=lead.get("reviews_text", ""),
                ai_summary=lead.get("ai_summary", ""),
            )
            lead_copy = dict(lead)
            lead_copy["cold_intro"] = intro
            result.append(lead_copy)
            print(f"   [{qi}/{len(qualifying)}] {name} → ✉️ Готово")
        else:
            result.append(dict(lead))

    print("\n💾 Збереження після Stage 4...")
    await save_leads(result)

    n_intros = sum(1 for l in result if l.get("cold_intro"))
    print(f"\n🚀 Готово! {len(result)} лідів, {n_intros} листів згенеровано.")


if __name__ == "__main__":
    asyncio.run(main())