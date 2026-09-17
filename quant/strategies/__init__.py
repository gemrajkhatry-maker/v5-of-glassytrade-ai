"""Strategies package — pluggable trading strategies.

Each strategy implements the TradingStrategy protocol from quant/strategy.py.
The default strategy is AmtScalpingStrategy, which encodes the Fabio Valentini
AMT scalping playbook.
"""

from quant.strategies.amt_scalping import AmtScalpingStrategy
from quant.strategies.selection import build_strategy

__all__ = ["AmtScalpingStrategy", "build_strategy"]
