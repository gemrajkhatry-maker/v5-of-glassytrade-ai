from dataclasses import dataclass

from quant.engine.submission_handler import SubmissionHandler
from quant.execution.exposure import ExposureStatus


@dataclass
class Fill:
    order_id: str
    requested_quantity: float
    filled_quantity: float
    fill_price: float


class PartialOMS:
    lot_size = 1.0

    def __init__(self):
        self.last_fill = None

    def submit(self, signal, quantity):
        self.last_fill = Fill("entry-1", quantity, 4, 100.0)
        return object()


class Risk:
    def position_size(self, *args, **kwargs):
        return 10


class PortfolioRisk:
    def __init__(self):
        self.reserved = 0.0
        self.released = 0.0

    def can_accept(self, *args, **kwargs):
        return True, "OK"

    def register_open(self, amount, **kwargs):
        self.reserved += amount
        return True

    def release(self, amount, **kwargs):
        self.released += amount


def test_partial_entry_keeps_risk_reservation_and_requires_reconciliation():
    from tests.quant.test_submission_handler_integration import FakeBar, FakePositionManager, make_signal

    exposure = None
    risk_reservation = 0.0
    portfolio_risk = PortfolioRisk()

    def set_exposure(value):
        nonlocal exposure
        exposure = value

    def set_risk(value):
        nonlocal risk_reservation
        risk_reservation = value

    handler = SubmissionHandler(
        config={"symbol": "NIFTY", "execution_enabled": True},
        deps={
            "risk": Risk(),
            "oms": PartialOMS(),
            "get_portfolio_risk": lambda: portfolio_risk,
            "get_position_manager": lambda: FakePositionManager(),
        },
        state={
            "get_bar_index": lambda: 10,
            "get_entry_bar_index": lambda: 0,
            "set_entry_bar_index": lambda value: None,
            "get_latch": lambda: {},
            "set_latch": lambda key, value: None,
            "pop_latch": lambda key: None,
            "get_open_trade_risk": lambda: risk_reservation,
            "set_open_trade_risk": set_risk,
            "get_exposure_state": lambda: exposure,
            "set_exposure_state": set_exposure,
        },
        emit=lambda event: None,
        latch_or_signal_block=lambda *args: None,
        notify_advisor_position=lambda *args: None,
    )

    assert handler.submit(
        make_signal(), FakeBar(), {}, type("RiskState", (), {"trades_today": 0, "equity": 1})(), "test"
    ) is True
    assert exposure.status is ExposureStatus.RECONCILIATION_REQUIRED
    assert portfolio_risk.reserved > 0
    assert portfolio_risk.released == 0


def test_unknown_entry_is_reconciliation_required_not_clean_rejection():
    from quant.execution.live_oms import ReconciliationRequiredError

    assert ReconciliationRequiredError("unknown", order_id="entry-unknown").order_id == "entry-unknown"
