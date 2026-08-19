"""Strategies package — pluggable trading strategies.

Each strategy implements the TradingStrategy protocol from quant/strategy.py.
The default strategy is AmtScalpingStrategy, which encodes the Fabio Valentini
AMT scalping playbook.
"""

from quant.strategies.amt_scalping import AmtScalpingStrategy

__all__ = ["AmtScalpingStrategy"]
