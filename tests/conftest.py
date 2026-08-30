import pytest
from contextlib import contextmanager
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.database import Base
from app.models import models  # noqa: F401  (registers tables on Base)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def reset_health_state():
    """Clear the cached last-scan time between tests.

    app.core.health keeps it in module state so /health never queries, which
    means it leaks across tests unless reset.
    """
    from app.core import health

    health._last_scan = None
    health._loaded = False
    yield
    health._last_scan = None
    health._loaded = False


@pytest.fixture
def mock_db(db_session):
    @contextmanager
    def _get_db():
        yield db_session

    with patch("app.portfolio.simulator.get_db", _get_db):
        yield db_session
