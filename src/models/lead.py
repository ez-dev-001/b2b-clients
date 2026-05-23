import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, func, Text, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


from src.core.database import Base

class Lead(Base):
    """
    Модель для зберігання лідів, зібраних з Google Maps.
    """
    __tablename__ = 'leads'

    # Унікальний ідентифікатор в нашій системі
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


    google_id: Mapped[str] = mapped_column(String, unique=True, index=True)

    # Основна інформація
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50), index=True)
    website: Mapped[str | None] = mapped_column(String(512))
    address: Mapped[str | None] = mapped_column(String(512))
    category: Mapped[str | None] = mapped_column(String(100))

    # Наш аналіз
    cms_type: Mapped[str | None] = mapped_column(String(50))
    reviews_text: Mapped[str | None] = mapped_column(Text)

    # --- НОВІ ПОЛЯ ДЛЯ AI ---
    clean_name: Mapped[str | None] = mapped_column(String(255))
    lead_score: Mapped[int | None] = mapped_column(Integer)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_processed: Mapped[bool | None] = mapped_column(Boolean, default=False)
    cold_intro: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(255))
    email_source: Mapped[str | None] = mapped_column(String(50))
    instagram: Mapped[str | None] = mapped_column(String(255))
    facebook: Mapped[str | None] = mapped_column(String(255))
    telegram: Mapped[str | None] = mapped_column(String(255))
    tiktok: Mapped[str | None] = mapped_column(String(255))

    # Службові поля
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str: 
        return f"<Lead(name='{self.name}', google_id='{self.google_id}')>"