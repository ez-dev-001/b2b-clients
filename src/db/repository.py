from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from src.models.lead import Lead

async def save_leads_to_db(session: AsyncSession, leads_data: list):
    if not leads_data: return

    for data in leads_data:
        stmt = insert(Lead).values(
            google_id=data.get("place_url"),
            name=data.get("name"),
            address=data.get("address"),
            phone=data.get("phone"),
            website=data.get("website"),
            reviews_text=data.get("reviews_text"),
            cms_type=data.get("cms_type"),
            clean_name=data.get("clean_name"),
            lead_score=data.get("lead_score"),
            ai_summary=data.get("ai_summary"),
            ai_processed=bool(data.get("lead_score") is not None),
            cold_intro=data.get("cold_intro"),
            email=data.get("email"),
            email_source=data.get("email_source"),
            instagram=data.get("instagram"),
            facebook=data.get("facebook"),
            telegram=data.get("telegram"),
            tiktok=data.get("tiktok"),
        ).on_conflict_do_update(
            index_elements=['google_id'],
            set_={
                "address": data.get("address"),
                "phone": data.get("phone"),
                "website": data.get("website"),
                "reviews_text": data.get("reviews_text"),
                "cms_type": data.get("cms_type"),
                "clean_name": data.get("clean_name"),
                "lead_score": data.get("lead_score"),
                "ai_summary": data.get("ai_summary"),
                "ai_processed": bool(data.get("lead_score") is not None),
                "cold_intro": data.get("cold_intro"),
                "email": data.get("email"),
                "email_source": data.get("email_source"),
                "instagram": data.get("instagram"),
                "facebook": data.get("facebook"),
                "telegram": data.get("telegram"),
                "tiktok": data.get("tiktok"),
            }
        )
        await session.execute(stmt)
    await session.commit()