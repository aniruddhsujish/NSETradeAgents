from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from contextlib import contextmanager
from app.core.config import settings
import structlog

logger = structlog.get_logger()


class Base(DeclarativeBase):
    """Declarative base every model inherits from."""

    pass


engine = create_engine(
    settings.database_url,
    connect_args=(
        {"check_same_thread": False} if "sqlite" in settings.database_url else {}
    ),
    pool_pre_ping=True,  # hosted Postgres drops idle connections; test before use
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_db():
    """Session context manager that commits on success and rolls back on error."""
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
    # Importing the module registers every model on Base before create_all.
    """Create any missing tables."""
    from app.models import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("database_initialised", url=settings.database_url)
