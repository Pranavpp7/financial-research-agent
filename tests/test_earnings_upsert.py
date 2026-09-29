"""Re-ingest earnings dedupe: same announcement date, remapped quarter."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.crud import apply_incoming_earnings
from backend.db.models import Company, Earning


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    # Only tables needed — avoid Base.metadata.create_all (pgvector columns).
    Company.__table__.create(engine)
    Earning.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        company = Company(ticker="TEST", name="Test Co")
        session.add(company)
        session.commit()
        session.refresh(company)
        yield session, company
    finally:
        session.close()
        engine.dispose()


def _quarters(session, company_id: int) -> list[str]:
    rows = (
        session.query(Earning)
        .filter(Earning.company_id == company_id)
        .order_by(Earning.quarter.asc())
        .all()
    )
    return [r.quarter for r in rows]


def test_stale_announcement_quarter_replaced_by_fiscal_quarter(db_session):
    session, company = db_session
    announcement = datetime(2024, 4, 25)

    session.add(
        Earning(
            company_id=company.id,
            quarter="2024-Q2",
            report_date=announcement,
            eps_actual=1.0,
        )
    )
    session.commit()

    apply_incoming_earnings(
        session,
        company.id,
        [
            {
                "quarter": "2024-Q1",
                "date": "2024-04-25",
                "eps_actual": 1.1,
                "eps_estimate": 1.0,
                "surprise_pct": 10.0,
            }
        ],
    )

    assert _quarters(session, company.id) == ["2024-Q1"]
    row = session.query(Earning).filter(Earning.company_id == company.id).one()
    assert row.report_date == announcement
    assert row.eps_actual == 1.1


def test_older_quarter_outside_incoming_window_is_kept(db_session):
    session, company = db_session

    session.add(
        Earning(
            company_id=company.id,
            quarter="2023-Q1",
            report_date=datetime(2023, 4, 27),
            eps_actual=0.5,
        )
    )
    session.commit()

    apply_incoming_earnings(
        session,
        company.id,
        [
            {
                "quarter": "2024-Q1",
                "date": "2024-04-25",
                "eps_actual": 1.1,
            }
        ],
    )

    assert _quarters(session, company.id) == ["2023-Q1", "2024-Q1"]


def test_empty_incoming_list_deletes_nothing(db_session):
    session, company = db_session

    session.add(
        Earning(
            company_id=company.id,
            quarter="2024-Q2",
            report_date=datetime(2024, 4, 25),
            eps_actual=1.0,
        )
    )
    session.commit()

    saved = apply_incoming_earnings(session, company.id, [])

    assert saved == 0
    assert _quarters(session, company.id) == ["2024-Q2"]
