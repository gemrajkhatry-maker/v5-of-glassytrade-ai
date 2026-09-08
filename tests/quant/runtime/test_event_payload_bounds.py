from quant.events import AmtUpdated, EventBus


def test_amt_updated_event_keeps_only_latest_footprint_snapshot():
    bus = EventBus()
    seen = []
    bus.subscribe(AmtUpdated, seen.append)
    footprints = {f"t{i}": {"levels": [{"price": float(i)}] * 3} for i in range(4)}
    bus.publish(AmtUpdated(symbol="X", time="t3", amt={"footprints": footprints, "poc": 1.0}))
    assert list(seen[0].amt["footprints"]) == ["t3"]
    assert seen[0].amt["poc"] == 1.0
