# tests/quant/contracts/test_services_boundaries.py
from app.domain.ops.startup_reconciliation import (
    ReconcilePolicy,
    ReconciliationResult,
    StartupReconciliation,
)
from quant.amt.session.scanner_config import ScannerConfig
from shared.reconnect import ReconnectPolicy


def test_ws_curve_preserved():
    p = ReconnectPolicy(base=5.0, cap=60.0, max_attempts=30)
    assert p.delay_for(0) == 5.0
    assert p.delay_for(1) == 10.0
    assert p.delay_for(10) == 60.0
    assert p.should_retry(29) is True
    assert p.should_retry(30) is False


def test_http_curve_preserved():
    p = ReconnectPolicy(base=0.5, cap=30.0, max_attempts=3)
    assert p.delay_for(0) == 0.5
    assert p.delay_for(1) == 1.0
    assert p.delay_for(10) == 30.0


def test_feed_curve_preserved():
    # feed: backoff starts 1.0, doubles each loop, capped at reconnect_sec
    p = ReconnectPolicy(base=1.0, cap=5.0, max_attempts=10**9)
    assert p.delay_for(1) == 2.0
    assert p.delay_for(0) == 1.0
    assert p.delay_for(10) == 5.0


# --- Task 2: ScannerConfig (REF-08) ---
# Verified defaults (Read 2026-09-03, NOT the plan's <D> placeholders):
# settings_adapter.py:129 "SCANNER_UNDERLYINGS", "CRUDEOIL,NATURALGAS,GOLDM,SILVERM"
# settings_adapter.py:153 int(os.getenv("SCANNER_TOP_N", "4"))
# settings_adapter.py:167 int(os.getenv("STRIKES_AROUND_ATM", "2"))  # NO SCANNER_ prefix
# settings_adapter.py:174 int(os.getenv("SCANNER_EXPIRY_INDEX", "0"))
# settings_adapter.py:181 os.getenv("SCANNER_OPTION_TYPE", "")
_SCANNER_ENV_KEYS = (
    "SCANNER_TOP_N",
    "SCANNER_UNDERLYINGS",
    "SCANNER_OPTION_TYPE",
    "SCANNER_EXPIRY_INDEX",
    "STRIKES_AROUND_ATM",
)


def test_from_env_defaults(monkeypatch):
    for k in _SCANNER_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    cfg = ScannerConfig.from_env()
    assert cfg.top_n == 4
    assert cfg.underlyings == ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM")
    assert cfg.option_type == ""
    assert cfg.preferred_option_type is None
    assert cfg.expiry_index == 0
    assert cfg.strikes_around_atm == 2


def test_from_env_parsing_matches_settings_adapter(monkeypatch):
    # settings_adapter strips but does NOT upper() and does NOT drop empties.
    monkeypatch.setenv("SCANNER_TOP_N", "8")
    monkeypatch.setenv("SCANNER_UNDERLYINGS", " crudeoil , GOLD ")
    monkeypatch.setenv("SCANNER_OPTION_TYPE", "CE")
    monkeypatch.setenv("SCANNER_EXPIRY_INDEX", "1")
    monkeypatch.setenv("STRIKES_AROUND_ATM", "3")
    cfg = ScannerConfig.from_env()
    assert cfg.top_n == 8
    assert cfg.underlyings == ("crudeoil", "GOLD")
    assert cfg.preferred_option_type == "CE"
    assert cfg.expiry_index == 1
    assert cfg.strikes_around_atm == 3


def test_from_settings_parity():
    class _FakeSettings:
        SCANNER_TOP_N = 6
        SCANNER_UNDERLYINGS = ["NIFTY", "BANKNIFTY"]
        SCANNER_OPTION_TYPE = ""
        SCANNER_EXPIRY_INDEX = 1
        STRIKES_AROUND_ATM = 3

    cfg = ScannerConfig.from_settings(_FakeSettings())
    assert cfg.top_n == 6
    assert cfg.underlyings == ("NIFTY", "BANKNIFTY")
    assert cfg.preferred_option_type is None
    kwargs = cfg.to_scan_kwargs(exchange="NSE")
    assert kwargs == {
        "n": 6,
        "underlyings": ["NIFTY", "BANKNIFTY"],
        "preferred_option_type": None,
        "exchange": "NSE",
        "expiry_index": 1,
        "strikes_around_atm": 3,
    }


# --- Task 4: Reconciliation policy, characterization (REF-09, Phase A) ---
# Tests 1, 2, 5 pin CURRENT behavior (must PASS pre-edit). Tests 3, 4, 6
# pin the new fail-safe default (added in Phase B; must FAIL pre-edit).


class _FakeReconStorage:
    def __init__(self, rows):
        self.rows = list(rows)
        self.deleted = []

    def load_open_positions(self):
        return list(self.rows)

    def delete_open_position(self, pos_id):
        self.deleted.append(pos_id)
        self.rows = [r for r in self.rows if r.get("id") != pos_id]


class _FakeReconBroker:
    def __init__(self, positions):
        self._positions = positions

    def get_positions(self):
        return list(self._positions)


def test_non_live_restores_without_broker(monkeypatch):
    monkeypatch.setattr("app.shared.mode.is_live_mode", lambda: False)

    class _ExplodingBroker:
        def get_positions(self):
            raise AssertionError("broker must not be called in non-live mode")

    store = _FakeReconStorage([{"id": "p1", "symbol": "NIFTY AUG FUT"}])
    result = StartupReconciliation(_ExplodingBroker(), store).reconcile()
    assert isinstance(result, ReconciliationResult)
    assert result.db_positions == 1
    assert result.broker_positions == 0
    assert result.restored == 1
    assert result.stale_removed == 0
    assert store.deleted == []


def test_live_match_restores(monkeypatch):
    monkeypatch.setattr("app.shared.mode.is_live_mode", lambda: True)
    store = _FakeReconStorage([{"id": "p1", "symbol": "NIFTY AUG FUT"}])
    broker = _FakeReconBroker([{"trading_symbol": "NIFTY AUG FUT"}])
    result = StartupReconciliation(broker, store).reconcile()
    assert isinstance(result, ReconciliationResult)
    assert result.restored == 1
    assert result.stale_removed == 0
    assert store.deleted == []


def test_live_broker_only_orphan_counted(monkeypatch):
    monkeypatch.setattr("app.shared.mode.is_live_mode", lambda: True)
    store = _FakeReconStorage([])
    broker = _FakeReconBroker([{"trading_symbol": "BANKNIFTY AUG FUT"}])
    result = StartupReconciliation(broker, store).reconcile()
    assert isinstance(result, ReconciliationResult)
    assert result.orphaned_registered == 1
    assert result.restored == 0


def test_live_db_only_quarantined_by_default(monkeypatch):
    monkeypatch.setattr("app.shared.mode.is_live_mode", lambda: True)
    store = _FakeReconStorage([{"id": "p1", "symbol": "NIFTY AUG FUT"}])
    result = StartupReconciliation(_FakeReconBroker([]), store).reconcile()
    assert result.stale_removed == 0
    assert store.deleted == []
    assert any(
        "quarantine" in d.lower() or "manual review" in d.lower()
        for d in result.discrepancies
    )


def test_live_db_only_deleted_with_explicit_policy(monkeypatch):
    monkeypatch.setattr("app.shared.mode.is_live_mode", lambda: True)
    store = _FakeReconStorage([{"id": "p1", "symbol": "NIFTY AUG FUT"}])
    broker = _FakeReconBroker([])
    result = StartupReconciliation(
        broker, store, policy=ReconcilePolicy.DELETE_STALE
    ).reconcile()
    assert result.stale_removed == 1
    assert store.deleted == ["p1"]


def test_live_case_insensitive_match_restores(monkeypatch):
    monkeypatch.setattr("app.shared.mode.is_live_mode", lambda: True)
    store = _FakeReconStorage([{"id": "p1", "symbol": "  nifty aug fut "}])
    broker = _FakeReconBroker([{"trading_symbol": "NIFTY AUG FUT"}])
    result = StartupReconciliation(broker, store).reconcile()
    assert result.restored == 1
    assert result.stale_removed == 0
    assert store.deleted == []
