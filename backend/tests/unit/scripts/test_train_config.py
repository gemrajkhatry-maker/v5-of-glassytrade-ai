"""Validates backend/scripts/mlx_lora_retrain.yaml mirrors the shipped adapter config."""

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CONFIG = _REPO_ROOT / "backend" / "scripts" / "mlx_lora_retrain.yaml"


def test_train_config_matches_shipped_adapter():
    cfg = yaml.safe_load(open(_CONFIG))
    assert cfg["model"] == "models/vibethinker-3b"
    assert cfg["data"] in ("amt_dataset/nifty_amt_data_livefmt", "amt_dataset/nifty_amt_data")
    assert cfg["iters"] == 300
    assert cfg["learning_rate"] == 2e-05
    assert cfg["num_layers"] == 16
    assert cfg["lora_parameters"]["rank"] == 8
    assert cfg["lora_parameters"]["scale"] == 20.0
    assert cfg["mask_prompt"] is True
