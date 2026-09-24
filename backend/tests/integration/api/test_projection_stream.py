from glassytrade.api.websocket.stream import ProjectionStream


def message(base, sequence):
    return {
        "schemaVersion": "1.0",
        "projectionVersion": 1,
        "projectionId": "runtime-main",
        "scope": {"type": "runtime"},
        "baseSequence": base,
        "sequence": sequence,
        "asOf": "2026-09-24T10:00:00+05:30",
        "releaseId": "release-test",
        "configFingerprint": "fp-test",
        "mode": "paper",
        "type": "delta",
        "payload": {},
    }


def test_stream_requests_resnapshot_on_sequence_gap():
    source = [message(1, 2), message(4, 6)]
    resnapshots = []

    async def collect():
        return [
            item
            async for item in ProjectionStream(
                source,
                on_resnapshot=lambda: resnapshots.append(True),
            )
        ]

    import asyncio

    result = asyncio.run(collect())
    assert len(result) == 1
    assert resnapshots == [True]
