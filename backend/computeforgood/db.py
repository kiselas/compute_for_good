from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20, connect_args={"connect_timeout": 3})
SessionLocal = sessionmaker(engine, expire_on_commit=False)
