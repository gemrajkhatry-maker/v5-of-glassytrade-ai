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

def test_accumulation_requires_near_poc():
    m = TripleAStateMachine()
    m.update(_bar(100), _vp(poc=100), _vwap(), None)
    m.update(_bar(100), _vp(poc=100), _vwap(), Absorption(0, 100, 500, "BUY", 0.5, 0))
    assert m.update(_bar(108), _vp(poc=100), _vwap(), None) == "ABSORBING"
    # 2 bars elapsed but closes far from POC (>= 4 steps) -> cannot accumulate
    assert m.update(_bar(110), _vp(poc=100), _vwap(), None) == "ABSORBING"
    assert m.phase == "ABSORBING"
    assert m.last_signal is None

def test_accumulation_near_poc():
    m = TripleAStateMachine()
    m.update(_bar(100), _vp(), _vwap(), None)
    m.update(_bar(100), _vp(), _vwap(), Absorption(0, 100, 500, "BUY", 0.5, 0))
    assert m.update(_bar(101), _vp(), _vwap(), None) == "ABSORBING"
    # 2 bars elapsed and close within 2 steps of POC
    assert m.update(_bar(102), _vp(), _vwap(), None) == "ACCUMULATING"

def test_accumulation_requires_poc_anchor():
    empty = VolumeProfile(levels=(), poc=0.0, vah=0.0, val=0.0, step=0.0,
                          total_volume=0.0)
    m = TripleAStateMachine()
    m.update(_bar(100), empty, _vwap(), None)
    m.update(_bar(100), empty, _vwap(), Absorption(0, 100, 500, "BUY", 0.5, 0))
    m.update(_bar(100), empty, _vwap(), None)
    # no POC anchor -> never near POC, stays ABSORBING even after 2 bars
    assert m.update(_bar(100), empty, _vwap(), None) == "ABSORBING"

def test_near_poc_step_mult_override():
    m = TripleAStateMachine(near_poc_step_mult=1.0)
    m.update(_bar(100), _vp(), _vwap(), None)
    m.update(_bar(100), _vp(), _vwap(), Absorption(0, 100, 500, "BUY", 0.5, 0))
    m.update(_bar(102), _vp(), _vwap(), None)
    # 2 steps from POC > mult=1 -> still ABSORBING
    assert m.update(_bar(103), _vp(), _vwap(), None) == "ABSORBING"

def test_cannot_skip_to_aggression():
    m = TripleAStateMachine()
    m.update(_bar(100), _vp(), _vwap(), None)
    assert m.update(_bar(105), _vp(), _vwap(), None) == "WAITING"  # no absorption

def test_resets_after_signal():
    m = TripleAStateMachine()
    m.update(_bar(100), _vp(), _vwap(), None)
    m.update(_bar(100), _vp(), _vwap(), Absorption(0, 100, 500, "BUY", 0.5, 0))
    m.update(_bar(101), _vp(), _vwap(), None)
    m.update(_bar(102), _vp(), _vwap(), None)  # near POC -> ACCUMULATING
    m.update(_bar(105), _vp(), _vwap(), None)  # breakout -> AGGRESSION -> LONG
    assert m.update(_bar(106), _vp(), _vwap(), None) == "WAITING"

def test_same_side_rearms_after_signal():
    m = TripleAStateMachine()
    m.update(_bar(100), _vp(), _vwap(), None)
    m.update(_bar(100), _vp(), _vwap(), Absorption(0, 100, 500, "BUY", 0.5, 0))
    m.update(_bar(101), _vp(), _vwap(), None)
    m.update(_bar(102), _vp(), _vwap(), None)  # near POC -> ACCUMULATING
    assert m.update(_bar(105), _vp(), _vwap(), None) == "AGGRESSION"  # LONG
    # fresh SAME-side absorption after AGGRESSION->WAITING must re-arm
    assert m.update(_bar(106), _vp(), _vwap(),
                    Absorption(0, 106, 500, "BUY", 0.5, 0)) == "ABSORBING"
    # and a subsequent near-POC accumulation + breakout reaches AGGRESSION/LONG again
    m.update(_bar(101), _vp(), _vwap(), None)
    m.update(_bar(102), _vp(), _vwap(), None)  # near POC -> ACCUMULATING
    assert m.update(_bar(110), _vp(), _vwap(), None) == "AGGRESSION"
    assert m.last_signal == "LONG"

def test_short_path():
    m = TripleAStateMachine()
    m.update(_bar(100), _vp(), _vwap(), None)
    m.update(_bar(100), _vp(), _vwap(), Absorption(0, 100, 500, "SELL", 0.5, 0))
    m.update(_bar(100), _vp(), _vwap(), None)  # 1st elapsed bar
    m.update(_bar(100), _vp(), _vwap(), None)  # 2nd elapsed bar near POC -> ACCUMULATING
    assert m.update(_bar(95), _vp(), _vwap(), None) == "AGGRESSION"  # far below VWAP-σ
    assert m.last_signal == "SHORT"
