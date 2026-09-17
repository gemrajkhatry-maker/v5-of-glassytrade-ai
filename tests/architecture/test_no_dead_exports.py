"""D-24b: functions with no production caller are deleted, not left to rot.

Each name below was audited (grep over quant/backend/tests) and found to have
zero production callers. Pinning them here stops a regression from quietly
re-introducing the dead API surface.
"""

import subprocess


# Pure exit-rule helpers with no production caller.
DEAD = [
    "update_peak_profit",
    "is_valid_rr",
    "update_excursions",  # tests-only caller; MAE/MFE never wired into exits
]

# Methods that were defined but never invoked from the live path.
DEAD_METHODS = [
    "_check_pyramid",  # runtime wrapper; pyramids run from PositionManager
]


def _definitions(pattern: str) -> str:
    out = subprocess.run(
        ["grep", "-rn", pattern, "quant"], capture_output=True, text=True
    )
    return out.stdout


def test_audited_dead_functions_are_gone():
    for name in DEAD:
        stdout = _definitions(f"def {name}")
        assert stdout.strip() == "", f"{name} still defined:\n{stdout}"


def test_audited_dead_methods_are_gone():
    for name in DEAD_METHODS:
        stdout = _definitions(f"def {name}")
        assert stdout.strip() == "", f"{name} still defined:\n{stdout}"


def test_strategies_satisfy_the_protocol():
    """TradingStrategy is runtime_checkable and the shipped strategy satisfies it."""
    from quant.strategies.amt_scalping import AmtScalpingStrategy
    from quant.strategy import TradingStrategy

    assert isinstance(AmtScalpingStrategy(), TradingStrategy)
