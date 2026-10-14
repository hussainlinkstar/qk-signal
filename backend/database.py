from sqlalchemy import create_engine

from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os

from core.env_bootstrap import bootstrap_environment

bootstrap_environment()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/dbname")

engine = create_engine(
    DATABASE_URL,
    connect_args={"connect_timeout": 5},
    pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
