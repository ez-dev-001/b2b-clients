import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# URL підключення (перевір, щоб пароль і назва бази збігалися з твоїм .env)
DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/gmaps_scraper"

engine = create_async_engine(DATABASE_URL, echo=False)

# Це та сама змінна, яку шукає run_scraper.py
async_session = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)

class Base(DeclarativeBase):
    pass