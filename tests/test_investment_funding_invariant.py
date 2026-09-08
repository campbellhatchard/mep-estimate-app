from __future__ import annotations

import pytest

from app.cip_models import CIPNonBillableAllocation
from app.models import EstimateRevision
from app.services.cip_phase_engine import calculation as cip_calculation


def _line(lines, key: str):
    return next(line for line in lines if line.key == key)


@pytest.mark.parametrize("investment_hours", [4.0, 52.0])
def test_cip_investment_reclassifies_funding_without_changing_effort_or_overhead(
    db_session,
    cip_revision_factory,
    investment_hours,
):
    """Investment is funding allocation, not incremental project effort.

    The business may fund part of an already-calculated task. That must reduce
    customer billable hours dollar-for-dollar while leaving gross task effort
    and all effort-derived calculations unchanged.
    """
    rev: EstimateRevision = cip_revision_factory()

    before_lines, before_summary, *_ = cip_calculation(db_session, rev)
    before_kickoff = _line(before_lines, "PLAN_KICKOFF")
    before_pm = _line(before_lines, "PLAN_PM")
    before_cont = _line(before_lines, "PLAN_CONTINGENCY")

    assert before_kickoff.task_hours >= investment_hours

    db_session.add(
        CIPNonBillableAllocation(
            revision_id=rev.id,
            line_key="PLAN_KICKOFF",
            hours=investment_hours,
            notes="Approved internal investment",
        )
    )
    db_session.flush()

    after_lines, after_summary, *_ = cip_calculation(db_session, rev)
    after_kickoff = _line(after_lines, "PLAN_KICKOFF")
    after_pm = _line(after_lines, "PLAN_PM")
    after_cont = _line(after_lines, "PLAN_CONTINGENCY")

    # Gross effort does not change when funding source changes.
    assert after_kickoff.task_hours == pytest.approx(before_kickoff.task_hours)
    assert after_summary["total_internal_hours"] == pytest.approx(
        before_summary["total_internal_hours"]
    )

    # Investment increases and customer-billable effort falls dollar-for-dollar.
    assert after_kickoff.investment_hours == pytest.approx(investment_hours)
    assert after_kickoff.billable_hours == pytest.approx(
        before_kickoff.task_hours - investment_hours
    )
    assert after_summary["investment_hours"] == pytest.approx(investment_hours)
    assert after_summary["billable_hours"] == pytest.approx(
        before_summary["billable_hours"] - investment_hours
    )

    # Funding allocation must not perturb derived effort.
    assert after_pm.task_hours == pytest.approx(before_pm.task_hours)
    assert after_cont.task_hours == pytest.approx(before_cont.task_hours)

    # Customer fees follow billable hours only.
    assert after_summary["fees"] == pytest.approx(
        before_summary["fees"] - investment_hours * float(rev.billing_rate)
    )
