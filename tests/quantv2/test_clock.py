from quantv2.clock import SessionClock


def test_nse_phases():
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    c = SessionClock("NSE")
    open_ts = datetime(2026, 9, 4, 10, 0, tzinfo=IST).timestamp()
    early = datetime(2026, 9, 4, 9, 0, tzinfo=IST).timestamp()
    fe = datetime(2026, 9, 4, 15, 25, tzinfo=IST).timestamp()
    assert c.is_open(open_ts) is True and c.is_open(early) is False
    assert c.force_exit(fe) is True and c.force_exit(open_ts) is False