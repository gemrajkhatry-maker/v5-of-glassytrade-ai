from quant.events import DepthUpdated, EventBus


def test_published_events_receive_monotonic_event_id():
    bus = EventBus()
    seen = []
    bus.subscribe(DepthUpdated, lambda event: seen.append(event.event_id))
    bus.publish(DepthUpdated(symbol="X", time="0", depth={}))
    bus.publish(DepthUpdated(symbol="X", time="0", depth={}))
    assert seen == ["1", "2"]
