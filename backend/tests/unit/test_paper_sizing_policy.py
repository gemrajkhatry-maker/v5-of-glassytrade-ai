"""Paper sizing policy tests.

Paper capital deployment is deliberately separate from stop-loss risk. The
95% paper policy must never be interpreted as risking 95% of equity at a stop.
"""

import pytest

from app.config_models import (
    ExchangeConfig,
    PaperConfig,
    RiskConfig,
    SymbolConfig,
    SystemConfig,
)
from app.config_models.validator import ConfigValidationError, validate_config


def _config(*, environment="paper", paper=None, risk=None):
    return SystemConfig(
        environment=environment,
        broker_mode="live" if environment == "live" else "paper",
        paper=paper or PaperConfig(),
        risk=risk or RiskConfig(),
        exchanges={
            "NSE": ExchangeConfig(
                name="NSE",
                symbols={"NIFTY": SymbolConfig(name="NIFTY")},
            )
        },
    )


def test_system_config_exposes_separate_paper_deployment_policy():
    config = _config()

    assert config.paper.capital_deployment_pct == pytest.approx(0.95)
    assert config.risk.risk_per_trade_pct == pytest.approx(0.005)


def test_paper_extreme_stop_risk_requires_explicit_opt_in():
    config = _config(risk=RiskConfig(risk_per_trade_pct=0.95))

    with pytest.raises(ConfigValidationError, match="allow_extreme_risk"):
        validate_config(config)


def test_paper_extreme_stop_risk_is_allowed_only_with_explicit_opt_in():
    config = _config(
        paper=PaperConfig(allow_extreme_risk=True),
        risk=RiskConfig(risk_per_trade_pct=0.95),
    )

    validate_config(config)


def test_live_rejects_extreme_stop_risk_even_when_paper_flag_is_enabled():
    config = _config(
        environment="live",
        paper=PaperConfig(allow_extreme_risk=True),
        risk=RiskConfig(risk_per_trade_pct=0.95),
    )

    with pytest.raises(ConfigValidationError, match="live.*risk_per_trade_pct"):
        validate_config(config)


def test_deployment_policy_is_not_used_as_stop_risk():
    config = _config(paper=PaperConfig(capital_deployment_pct=0.95))

    validate_config(config)
    assert config.paper.capital_deployment_pct == pytest.approx(0.95)
    assert config.risk.risk_per_trade_pct == pytest.approx(0.005)


def test_deployment_policy_must_be_between_zero_and_one():
    config = _config(paper=PaperConfig(capital_deployment_pct=1.01))

    with pytest.raises(ConfigValidationError, match="capital_deployment_pct"):
        validate_config(config)
