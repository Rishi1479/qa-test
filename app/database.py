# pyrefly: ignore [missing-import]
from sqlalchemy import create_engine
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import Generator
from app.config import settings

# If using Postgres, use psycopg driver which we installed via psycopg[binary]
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    db_url,
    echo=False,
    # Supabase uses connection pooling (pgbouncer) often, so pool_pre_ping is good
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db() -> Generator:
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
