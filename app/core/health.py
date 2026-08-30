"""Liveness state for the /health endpoint.

Lives outside the API layer so the scan can report in without importing
FastAPI — main.py drives the pipeline and should not depend on the web app.
"""

from datetime import datetime

from sqlalchemy import desc

from app.core.database import get_db
from app.models.models import ScanRun

# Long enough to survive a weekend plus a Monday holiday.
MAX_SCAN_AGE_HOURS = 96

_last_scan: datetime | None = None
_loaded = False


def note_scan_run(at: datetime) -> None:
    """Record in memory that a scan just finished."""
    global _last_scan, _loaded
    _last_scan = at
    _loaded = True


def last_scan_at() -> datetime | None:
    """When the last scan ran, hitting the database only on a cold process.

    An external monitor polls /health constantly. A query per poll would keep
    hosted Postgres permanently awake, so the answer is cached after the first
    read and refreshed by note_scan_run.
    """
    global _last_scan, _loaded
    if not _loaded:
        with get_db() as db:
            row = db.query(ScanRun).order_by(desc(ScanRun.ran_at)).first()
        _last_scan = row.ran_at if row else None
        _loaded = True
    return _last_scan
