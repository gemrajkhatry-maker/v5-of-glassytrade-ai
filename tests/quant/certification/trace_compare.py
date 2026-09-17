"""Normalize event payloads and compare traces byte-exactly.

Volatile keys stripped recursively: engine-assigned ids that legitimately
differ between two independent engines (event counter, correlation UUID,
position UUIDs). Everything else must match exactly.
"""

from __future__ import annotations

# Keys that identify a run-local object rather than behaviour. position_id is
# derived from the position's internal _id (uuid) so two runs that trade
# identically still emit different StopMoved.position_id values.
_VOLATILE_KEYS = frozenset({"event_id", "correlation_id", "_id", "position_id"})


def normalize(obj):
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items() if k not in _VOLATILE_KEYS}
    if isinstance(obj, (list, tuple)):
        return type(obj)(normalize(v) for v in obj) if isinstance(obj, tuple) else [
            normalize(v) for v in obj
        ]
    return obj


def _as_dict(evt) -> dict:
    d = evt.__class__.__name__
    from dataclasses import asdict
    return {"__event__": d, **normalize(asdict(evt))}


_MISSING = object()


def _strict_eq(a, b) -> bool:
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_strict_eq(v, b[k]) for k, v in a.items())
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_strict_eq(x, y) for x, y in zip(a, b))
    return a == b


def traces_equal(a: list, b: list) -> bool:
    return first_divergence(a, b) is None


def first_divergence(a: list, b: list) -> str | None:
    da = [_as_dict(e) for e in a]
    db = [_as_dict(e) for e in b]
    for i, (x, y) in enumerate(zip(da, db)):
        keys = set(x) | set(y)
        diff = {k for k in keys if not _strict_eq(x.get(k, _MISSING), y.get(k, _MISSING))}
        if diff:
            return f"index={i} type={x.get('__event__')} differing_keys={sorted(diff)}"
    if len(da) != len(db):
        return f"length mismatch: {len(da)} vs {len(db)}"
    return None
