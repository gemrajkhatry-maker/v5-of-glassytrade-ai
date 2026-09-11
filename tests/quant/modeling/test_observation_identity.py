from quant.modeling.observation import ForecastObservationIdentity


def test_observation_identity_requires_source_and_timestamp():
    identity = ForecastObservationIdentity(
        symbol="NIFTY",
        source_symbol="NIFTY FUT",
        timeframe_seconds=300,
        observed_at="2026-09-11T09:20:00+05:30",
        bar_index=7,
        close=100.0,
        is_complete=True,
    )
    assert identity.symbol == "NIFTY"
    assert identity.source_symbol == "NIFTY FUT"
    assert identity.is_complete is True


def test_different_time_or_close_is_not_same_observation():
    base = ForecastObservationIdentity("NIFTY", "NIFTY FUT", 300, "t1", 7, 100.0, True)
    assert base != ForecastObservationIdentity("NIFTY", "NIFTY FUT", 300, "t2", 7, 100.0, True)
    assert base != ForecastObservationIdentity("NIFTY", "NIFTY FUT", 300, "t1", 7, 101.0, True)


def test_forming_observation_is_distinguishable():
    complete = ForecastObservationIdentity("NIFTY", "NIFTY", 60, "t1", 1, 100.0, True)
    forming = ForecastObservationIdentity("NIFTY", "NIFTY", 60, "t1", 1, 100.0, False)
    assert complete != forming
