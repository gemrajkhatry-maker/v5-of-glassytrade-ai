"""Tests for the orderflow dashboard endpoints (via OrderflowService)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from tradex_domain.instruments import Equity
from tradex_domain.market import Depth, Quote
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.interface.fastapi_app import create_app

INSTRUMENT = Equity.of("NSE", "RELIANCE")
KEY = "NSE:RELIANCE"
T0 = datetime(2026, 8, 8, 9, 15, 0, tzinfo=UTC)


def _quote(ltp: float, bid: float, ask: float, vol: float = 100) -> Quote:
    return Quote(
        instrument=INSTRUMENT,
        ltp=Price(value=Decimal(str(ltp))),
        bid=Price(value=Decimal(str(bid))),
        ask=Price(value=Decimal(str(ask))),
        volume=Quantity(value=Decimal(str(vol))),
        timestamp=T0,
    )


def _depth() -> Depth:
    return Depth(
        instrument=INSTRUMENT,
        bids=((Price(Decimal("99")), Quantity(Decimal("100"))),),
        asks=((Price(Decimal("101")), Quantity(Decimal("50"))),),
        timestamp=T0,
    )


def test_orderflow_endpoints_empty_when_no_data() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.get(f"/orderflow/delta/{KEY}").status_code == 404
    assert client.get(f"/orderflow/volume-profile/{KEY}").status_code == 404
    assert client.get(f"/orderflow/orderbook/{KEY}").status_code == 404


def test_orderflow_endpoints_after_feed() -> None:
    app = create_app()
    svc = app.state.orderflow
    svc.on_quote(_quote(100.5, 100.0, 100.5, 100))  # buy at ask
    svc.on_depth(_depth())

    client = TestClient(app)
    fp = client.get(f"/orderflow/footprint/{KEY}")
    assert fp.status_code == 200
    assert "100.5" in fp.json()["levels"]

    ob = client.get(f"/orderflow/orderbook/{KEY}")
    assert ob.status_code == 200
    assert ob.json()["best_bid"] == 99.0

    vp = client.get(f"/orderflow/volume-profile/{KEY}")
    assert vp.status_code == 200
    assert vp.json()["total_volume"] == 100.0

    signals = client.get(f"/orderflow/signals/{KEY}")
    assert signals.status_code == 200
    assert signals.json() == []


def _feed_4_level_profile(svc: object) -> None:
    """Feed quotes so the profile is {100.0:100, 100.5:300, 101.0:200, 101.5:100}."""
    svc.on_quote(_quote(100.5, 100.0, 100.5, 300))  # buy at 100.5
    svc.on_quote(_quote(100.0, 100.0, 100.5, 100))  # sell at 100.0
    svc.on_quote(_quote(101.0, 100.5, 101.0, 200))  # buy at 101.0
    svc.on_quote(_quote(101.5, 101.0, 101.5, 100))  # buy at 101.5


def test_volume_profile_value_area_pct_query_param() -> None:
    app = create_app()
    _feed_4_level_profile(app.state.orderflow)
    client = TestClient(app)

    default = client.get(f"/orderflow/volume-profile/{KEY}")
    assert default.status_code == 200
    body = default.json()
    assert body["value_area_pct"] == 0.68  # echoed default (68% rule)
    assert body["vah"] == 101.0 and body["val"] == 100.5

    # A narrower value area must produce a tighter (or equal) band.
    narrow = client.get(f"/orderflow/volume-profile/{KEY}", params={"value_area_pct": 0.3})
    assert narrow.status_code == 200
    n = narrow.json()
    assert n["value_area_pct"] == 0.3
    assert n["vah"] - n["val"] <= body["vah"] - body["val"]

    # Service-level override works too (per-request, without touching the service default).
    svc_wide = app.state.orderflow.volume_profile(KEY, value_area_pct=0.99)
    assert svc_wide is not None and svc_wide.vah == 101.5 and svc_wide.val == 100.0


def test_volume_profile_value_area_pct_validation() -> None:
    app = create_app()
    _feed_4_level_profile(app.state.orderflow)
    client = TestClient(app)
    url = f"/orderflow/volume-profile/{KEY}"
    assert client.get(url, params={"value_area_pct": 1.5}).status_code == 422
    assert client.get(url, params={"value_area_pct": 0}).status_code == 422
    assert client.get(url, params={"value_area_pct": -0.1}).status_code == 422
