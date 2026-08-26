from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return a timezone-naive UTC datetime for compatibility with existing DB columns.

    `datetime.utcnow()` is deprecated in Python 3.12. The application schema stores
    naive UTC timestamps, so normalize an aware UTC value back to naive form at this
    boundary rather than changing persisted timestamp semantics in a hardening release.
    """
    return datetime.now(UTC).replace(tzinfo=None)
