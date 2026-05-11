import pytest
from contextlib import contextmanager
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.database import Base
from app.models.models import Trade, PortfolioSnapshot  # noqa: F401


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def mock_db(db_session):
    @contextmanager
    def _get_db():
        yield db_session

    with patch("app.portfolio.simulator.get_db", _get_db):
        yield db_session
