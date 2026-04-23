from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from contextlib import contextmanager
from app.core.config import settings
import structlog

logger = structlog.get_logger()


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args=(
        {"check_same_thread": False} if "sqlite" in settings.database_url else {}
    ),
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("database_error", error=str(e))
        raise
    finally:
        db.close()


def init_db():
    from app.models.models import Trade, PortfolioSnapshot, WatchlistStock

    Base.metadata.create_all(bind=engine)
    logger.info("database_initialised", url=settings.database_url)
