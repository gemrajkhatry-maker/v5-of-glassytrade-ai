import json
from quant.advisory.chat import ChatClient, ChatMessage
from quant.advisory.entry_journal import EntryJournal
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState

class FakeClient:
    def __init__(self, response='{"direction":"LONG","confidence":0.7,"rationale":"x"}'):
        self.response = response
        self.calls = []
    def complete(self, messages, max_tokens=200):
        self.calls.append(messages)
        return self.response

def _state():
    return AuctionState(
        time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=101, lower_1=99, upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0, cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )

def test_prompt_includes_state_and_prompt_is_journaled():
    fc = FakeClient()
    j = EntryJournal(fc)
    e = j.analyze(_state(), "SYM")
    assert e.decision == "LONG"
    assert e.symbol == "SYM"
    assert "POC" in e.prompt.upper() and "VWAP" in e.prompt.upper()
    assert len(j.entries) == 1

def test_invalid_json_falls_back_to_flat():
    fc = FakeClient(response="not json")
    j = EntryJournal(fc)
    e = j.analyze(_state())
    assert e.decision == "FLAT" and e.confidence == 0.0

def test_never_executes():
    # advisory is journaled-only: analyze must not mutate anything outside the journal
    fc = FakeClient()
    j = EntryJournal(fc)
    e = j.analyze(_state())
    assert e.decision in ("LONG", "SHORT", "FLAT")
