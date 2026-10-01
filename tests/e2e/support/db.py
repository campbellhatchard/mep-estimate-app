from __future__ import annotations

from contextlib import contextmanager

from app.database import SessionLocal


@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
