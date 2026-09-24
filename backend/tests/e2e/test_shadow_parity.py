from glassytrade.application.runtime.shadow import ShadowRunner


def test_shadow_has_no_broker_write_capability():
    runner = ShadowRunner(None)
    assert runner.broker_write_capability is False


def test_shadow_comparison_reports_semantic_difference():
    runner = ShadowRunner(None)
    report = runner.compare(
        {"positions": [{"contractId": "NIFTY", "quantity": 1}], "sequence": 4},
        {"positions": [{"contractId": "NIFTY", "quantity": 2}], "sequence": 4},
    )
    assert report.matches is False
    assert report.differences
