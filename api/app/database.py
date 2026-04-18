from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL.replace("postgresql://", "postgresql+pg8000://"), 
    pool_pre_ping=True, # Restaurado para estabilidade. Evita 'stale connections' que quebram o site.
    pool_size=10, 
    max_overflow=20,
    pool_recycle=1800, # 30 min recycler
    pool_timeout=30 
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
