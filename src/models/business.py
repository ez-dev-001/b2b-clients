from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, JSON, DateTime
from datetime import datetime
from src.core.database import Base

class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    address: Mapped[str] = mapped_column(String(500), nullable=True)
    phone: Mapped[str] = mapped_column(String(50), nullable=True)
    website: Mapped[str] = mapped_column(String(255), nullable=True)
    rating: Mapped[float] = mapped_column(nullable=True)
    reviews_count: Mapped[int] = mapped_column(nullable=True)
    google_maps_url: Mapped[str] = mapped_column(String(1000), unique=True)
    
    # Raw data and enrichment
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    enriched_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
