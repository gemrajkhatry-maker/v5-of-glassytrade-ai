from decimal import Decimal

from glassytrade.application.runtime.paper_acceptance import evaluate_paper_acceptance


def test_paper_acceptance_requires_full_session_and_eod_evidence():
    report = evaluate_paper_acceptance(
        {
            "session_complete": True,
            "eod_verified": True,
            "reconciliation_clean": True,
            "unresolved_cases": 0,
            "max_loss": Decimal("0.01"),
            "loss_limit": Decimal("0.02"),
        }
    )
    assert report.accepted is True
    assert report.evidence["eod_verified"] is True


def test_paper_acceptance_blocks_unknown_reconciliation():
    report = evaluate_paper_acceptance(
        {
            "session_complete": True,
            "eod_verified": False,
            "reconciliation_clean": False,
            "unresolved_cases": 1,
            "max_loss": Decimal("0.01"),
            "loss_limit": Decimal("0.02"),
        }
    )
    assert report.accepted is False
    assert report.reasons
