"""Backward compatibility shim — use exit_engine.py directly.

All public names that previously lived here are re-exported from
``app.domain.fabio_ai.services.exit_engine``.

Do NOT add new logic to this file.  Update callers to import from
``exit_engine`` instead.

New decomposed services are also available:
- exit_rules.py: Pure exit rule functions
- trail_engine.py: Trailing stop logic
- scale_manager.py: Scale-in management
- loss_tracker.py: Daily loss tracking
"""

from __future__ import annotations

from app.domain.fabio_ai.services.exit_engine import (  # noqa: F401
    CushionState,
    ExitDecision,
    ExitEngine,
    ExitEngine as TradeManager,
    ExitReason,
    ExitSignal,
    MarketStateCodec,
    TIME_STOP_TABLE,
    EXPIRY_TIME_STOP,
    TradeManagerConfig,
)

# Also export the new decomposed services for direct access
from app.domain.fabio_ai.services.trail_engine import TrailEngine  # noqa: F401
from app.domain.fabio_ai.services.scale_manager import ScaleManager  # noqa: F401
from app.domain.fabio_ai.services.loss_tracker import LossTracker  # noqa: F401
from app.domain.fabio_ai.services.exit_rules import (  # noqa: F401
    check_stop_loss,
    check_time_stop_with_price,
    check_scratch,
    update_excursions,
    update_peak_profit,
    check_spread_blowout,
    get_session_time_stop,
    is_valid_rr,
)
