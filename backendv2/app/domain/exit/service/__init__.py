"""Exit domain services."""

from app.domain.exit.service.exit_engine import ExitEngine, PartitionExitManager as PartitionExitManagerLegacy, TrailEngine
from app.domain.exit.service.exit_rules import check_spread_blowout, check_time_stop, classify_exit
from app.domain.exit.service.loss_tracker import LossTracker
from app.domain.exit.service.partition_exit_manager import PartitionExitManager as PartitionExitManagerV2
from app.domain.exit.service.pyramid_manager import PyramidManager
from app.domain.exit.service.position_sizer import PositionSizer, PositionSize
from app.domain.exit.service.structural_stop_engine import compute_structural_stop

__all__ = [
    "ExitEngine",
    "TrailEngine",
    "PartitionExitManagerLegacy",
    "PartitionExitManagerV2",
    "check_spread_blowout",
    "check_time_stop",
    "classify_exit",
    "LossTracker",
    "PyramidManager",
    "PositionSizer",
    "PositionSize",
    "compute_structural_stop",
]
