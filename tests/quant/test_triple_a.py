from quant.bars import Bar
from quant.volume_profile import VolumeProfile, VolumeProfileLevel
from quant.vwap import VWAPState
from quant.absorption import Absorption
from quant.triple_a import TripleAStateMachine

def _vp(poc=101.0):
    return VolumeProfile(levels=(), poc=poc, vah=102, val=100, step=1, total_volume=100)

def _vwap(value=100.0, std=2.0):
    return VWAPState(value=value, upper_1=value+std, lower_1=value-std,
                     upper_2=value+2*std, lower_2=value-2*std, std=std, deviation_sigmas=0)

def _bar(close, vol=100):
    return Bar(time="t", open=close, high=close+1, low=close-1, close=close, volume=vol)

def test_phases_progress_in_order():
    m = TripleAStateMachine()
    assert m.update(_bar(100), _vp(), _vwap(), None) == "WAITING"
    assert m.update(_bar(100), _vp(), _vwap(),
                    Absorption(0, 100, 500, "BUY", 0.5, 0)) == "ABSORBING"
    assert m.update(_bar(100), _vp(), _vwap(), None) == "ABSORBING"
    assert m.update(_bar(101), _vp(), _vwap(), None) == "ACCUMULATING"  # near POC
    assert m.update(_bar(105), _vp(), _vwap(), None) == "AGGRESSION"    # above VWAP+σ
    assert m.last_signal == "LONG"

def test_cannot_skip_to_aggression():
    m = TripleAStateMachine()
    m.update(_bar(100), _vp(), _vwap(), None)
    assert m.update(_bar(105), _vp(), _vwap(), None) == "WAITING"  # no absorption

def test_resets_after_signal():
    m = TripleAStateMachine()
    m.update(_bar(100), _vp(), _vwap(), None)
    m.update(_bar(100), _vp(), _vwap(), Absorption(0, 100, 500, "BUY", 0.5, 0))
    m.update(_bar(101), _vp(), _vwap(), None)
    m.update(_bar(105), _vp(), _vwap(), None)  # AGGRESSION -> LONG
    assert m.update(_bar(106), _vp(), _vwap(), None) == "WAITING"

def test_short_path():
    m = TripleAStateMachine()
    m.update(_bar(100), _vp(), _vwap(), None)
    m.update(_bar(100), _vp(), _vwap(), Absorption(0, 100, 500, "SELL", 0.5, 0))
    m.update(_bar(99), _vp(), _vwap(), None)
    m.update(_bar(95), _vp(), _vwap(), None)  # below VWAP-σ
    assert m.last_signal == "SHORT"
