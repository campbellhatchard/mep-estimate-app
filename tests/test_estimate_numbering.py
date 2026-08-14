from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.estimate_numbering import EstimateNumberSequence, next_estimate_number


def test_estimate_number_is_yyyymmnnn_and_resets_each_month():
    engine = create_engine("sqlite:///:memory:")
    EstimateNumberSequence.__table__.create(engine)

    with Session(engine) as db:
        assert next_estimate_number(db, date(2026, 6, 30)) == "202606001"
        db.commit()
        assert next_estimate_number(db, date(2026, 6, 30)) == "202606002"
        db.commit()
        assert next_estimate_number(db, date(2026, 7, 1)) == "202607001"
        db.commit()
        assert next_estimate_number(db, date(2026, 7, 1)) == "202607002"
        db.commit()
        assert next_estimate_number(db, date(2027, 1, 1)) == "202701001"
        db.commit()


def test_estimate_number_is_always_nine_numeric_digits():
    engine = create_engine("sqlite:///:memory:")
    EstimateNumberSequence.__table__.create(engine)

    with Session(engine) as db:
        number = next_estimate_number(db, date(2026, 8, 14))
        assert number == "202608001"
        assert len(number) == 9
        assert number.isdigit()
