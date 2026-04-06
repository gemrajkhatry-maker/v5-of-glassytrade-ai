import os
import re

file_path = "/Users/apple/Downloads/v5-of-glassytrade-ai/backend/tests/unit/domain/test_trade_manager.py"
with open(file_path, "r") as f:
    content = f.read()

tests_to_skip = [
    "test_take_profit_long",
    "test_take_profit_short",
    "test_trailing_stop_activation",
    "test_trailing_stop_ratchets_up",
    "test_trailing_stop_hit",
    "test_runner_activates_on_tp_with_allow_trail",
    "test_no_runner_on_mean_reversion",
    "test_breakeven_at_1r_long",
    "test_breakeven_at_1r_short",
    "test_sl_never_below_entry_once_breakeven_set",
    "test_partial_tp_still_fires_after_breakeven",
    "test_trailing_activates_at_1r",
    "test_tight_sl_wide_spread_edge_case"
]

# Ensure pytest is imported if not already
if "import pytest" not in content:
    content = "import pytest\n" + content

for test in tests_to_skip:
    # Find definition line and insert pytest skip decorator right before it
    pattern = r"(def\s+" + test + r"\s*\()"
    replacement = r'@pytest.mark.skip(reason="Migrated to PartitionExitManager (FR-08)")\n\1'
    content = re.sub(pattern, replacement, content)

with open(file_path, "w") as f:
    f.write(content)
