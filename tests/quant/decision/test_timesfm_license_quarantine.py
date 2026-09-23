import pytest
from quant.decision import timesfm_engine as eng_mod


def test_model_load_blocked_without_commercial_ack(monkeypatch):
    monkeypatch.setenv("TIMESFM_COMMERCIAL_ACK", "0")
    eng_mod.reset_timesfm_model_cache()
    monkeypatch.setattr(eng_mod, "_TIMESFM_MODEL", None)
    # Stub the heavy import so the test never downloads weights:
    import sys
    import types
    fake = types.ModuleType("timesfm")
    fake.TimesFM3Forecaster = types.SimpleNamespace(
        from_pretrained=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not load"))
    )
    monkeypatch.setitem(sys.modules, "timesfm", fake)
    with pytest.raises(RuntimeError, match="COMMERCIAL_ACK"):
        eng_mod.get_timesfm_model()
