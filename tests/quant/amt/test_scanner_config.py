"""D-23: one settings authority for the scanner knobs."""


def test_scanner_config_has_one_construction_path():
    """D-23: from_env and from_settings read the same vars with different
    defaults (SCANNER_TOP_N was 4, 4 and 8 across three authorities)."""
    from quant.amt.session import scanner_config

    assert not hasattr(scanner_config.ScannerConfig, "from_env"), (
        "from_env duplicates the settings adapter and must be removed"
    )


def test_top_n_has_a_single_default(monkeypatch):
    from types import SimpleNamespace
    from quant.amt.session.scanner_config import ScannerConfig

    settings = SimpleNamespace(
        SCANNER_TOP_N=None, SCANNER_UNDERLYINGS=None, SCANNER_OPTION_TYPE=None,
        SCANNER_EXPIRY_INDEX=None, STRIKES_AROUND_ATM=None,
    )
    cfg = ScannerConfig.from_settings(settings)
    assert cfg.top_n == ScannerConfig.DEFAULT_TOP_N
