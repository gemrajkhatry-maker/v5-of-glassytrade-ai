"""Tests for portfolio scale-in integration."""


def test_portfolio_add_to_position():
    """Portfolio.add_to_position scales into winning position."""
    from quant.contracts.aggregates import Portfolio

    portfolio = Portfolio.create_default()

    # Create a mock signal
    from quant.contracts.entities import Signal, SignalType, Source, SetupType
    import time

    signal = Signal.create(
        type=SignalType.BUY,
        price=100.0,
        reason="Test",
        stop_loss=98.0,
        take_profit=104.0,
        timestamp=str(time.time()),
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
    )

    # Open position with 40% scale (first entry)
    position = portfolio.open_position(signal, "NIFTY", scale_fraction=0.4)
    assert position is not None
    assert position.size > 0

    # Add 30% (second entry)
    success = portfolio.add_to_position(position.id, 0.3, 101.0)
    assert success

    # Add 30% (third entry)
    success = portfolio.add_to_position(position.id, 0.3, 102.0)
    assert success
