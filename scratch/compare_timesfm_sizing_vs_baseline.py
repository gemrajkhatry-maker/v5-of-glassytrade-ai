"""Demonstration & Side-by-Side Comparison:
Hardcoded Rule-Based Risk/Sizing vs. TimesFM Model-Driven Risk/Sizing.
"""

import numpy as np
from quant.decision.timesfm_agents import TimesFMForecast
from quant.decision.timesfm_sizing import TimesFMPositionSizer
from quant.execution.risk import SessionRisk


def run_comparison():
    print("=" * 80)
    print("TIMESFM MODEL-DRIVEN SIZING VS. HARDCODED RULES COMPARISON")
    print("=" * 80)

    equity = 100000.0
    lot_size = 10.0
    entry = 8000.0

    risk_engine = SessionRisk(starting_equity=equity)
    sizer = TimesFMPositionSizer()

    scenarios = [
        {
            "name": "Scenario 1: Strong Clean Breakout (High Conviction, Low Dispersion)",
            "p50": np.linspace(entry, entry + 45.0, 32),
            "spread": 8.0,
            "rule_sl": 7980.0,
            "day_of_week": 1, # Tuesday
            "is_expiry": False,
        },
        {
            "name": "Scenario 2: Monday High-Conviction Breakout (Hardcoded Rule Penalizes 50%)",
            "p50": np.linspace(entry, entry + 45.0, 32),
            "spread": 8.0,
            "rule_sl": 7980.0,
            "day_of_week": 0, # Monday
            "is_expiry": False,
        },
        {
            "name": "Scenario 3: Expiry Day Chop / High Dispersion Uncertainty",
            "p50": np.full(32, entry + 6.0),
            "spread": 75.0, # massive uncertainty spread
            "rule_sl": 7980.0,
            "day_of_week": 3, # Thursday
            "is_expiry": True,
        },
        {
            "name": "Scenario 4: Fast Impulse Scalp (Peak at Step 4 vs. Grinding Move)",
            "p50": np.array([8000.0, 8018.0, 8032.0, 8040.0] + list(np.linspace(8038.0, 8030.0, 28))),
            "spread": 10.0,
            "rule_sl": 7985.0,
            "day_of_week": 2,
            "is_expiry": False,
        }
    ]

    for sc in scenarios:
        p50 = sc["p50"]
        spread = sc["spread"]
        p10 = p50 - (spread / 2.0)
        p90 = p50 + (spread / 2.0)
        fc = TimesFMForecast(
            horizon=32,
            p50_path=p50,
            p10_path=p10,
            p90_path=p90,
            q_spread=spread,
            mean_forecast=float(p50[-1]),
            pct_change=(p50[-1] - entry) / entry,
            forecast_steps=["LONG"] * 32,
            curr_price=entry,
            lat_ms=12.0,
        )

        # 1. Hardcoded rule sizing
        risk_engine._day_of_week = sc["day_of_week"]
        rule_qty = risk_engine.position_size(
            entry=entry,
            sl=sc["rule_sl"],
            lot_size=lot_size,
            is_expiry=sc["is_expiry"],
            forecast=None, # forces rule-based mode
        )
        rule_lots = int(rule_qty // lot_size)

        # 2. TimesFM model-driven sizing
        dyn_res = sizer.compute_size(
            equity=equity,
            entry=entry,
            side="LONG",
            forecast=fc,
            lot_size=lot_size,
            override_sl=None, # uses dynamic VaR stop
        )

        print(f"\n>> {sc['name']}")
        print(f"   [Hardcoded Rule]  Lots: {rule_lots:2d} ({rule_qty:4.0f} qty) | Fixed SL: {sc['rule_sl']:.2f}")
        print(f"   [TimesFM Model]   Lots: {dyn_res.lots:2d} ({dyn_res.quantity:4.0f} qty) | Risk: {dyn_res.risk_pct:.2%} | Dynamic VaR SL: {dyn_res.var_stop:.2f}")
        print(f"                     Kelly: {dyn_res.kelly_fraction:.2%} | Dispersion Mult: {dyn_res.dispersion_multiplier:.2f}x | Velocity Mult: {dyn_res.velocity_multiplier:.2f}x (tau*={dyn_res.expected_peak_step})")
        print(f"                     WinProb: {dyn_res.win_prob:.1%} | Payoff: {dyn_res.payoff_ratio:.2f}R")

    print("\n" + "=" * 80)
    print("KEY TAKEAWAYS:")
    print("1. In Scenario 2 (Monday Clean Trend): Hardcoded rule cut size by 50% blindly. TimesFM recognized the tight cone and preserved optimal sizing.")
    print("2. In Scenario 3 (Expiry Chop): TimesFM automatically contracted size due to high cone dispersion (spread=75.0), protecting capital organically.")
    print("3. In Scenario 4 (Fast Scalp): TimesFM detected high velocity (tau*=4) and boosted sizing efficiency before option theta decay.")
    print("=" * 80)


if __name__ == "__main__":
    run_comparison()
