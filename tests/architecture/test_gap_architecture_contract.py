from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "quant/decision/gap_architecture.workflow.json"
HTML_PATH = ROOT / "quant/decision/gap_architecture.workflow.html"


def test_gap_architecture_declares_durable_runtime_edges():
    artifact = json.loads(JSON_PATH.read_text())
    edges = {(edge["from"], edge["to"]): edge for edge in artifact["edges"]}
    required = {
        ("signal", "durable-intent"),
        ("durable-intent", "oms-broker"),
        ("oms-broker", "normalized-fill"),
        ("normalized-fill", "reconciliation"),
        ("reconciliation", "position-manager"),
        ("position-manager", "event-store"),
        ("event-store", "canonical-projection"),
        ("canonical-projection", "websocket-ui"),
        ("ctx", "narrative"),
    }
    assert required <= set(edges)
    assert edges[("ctx", "narrative")]["variant"] == "dashed"
    assert "exact Fabio parity" not in json.dumps(artifact).lower()


def test_gap_architecture_html_matches_durable_runtime_vocabulary():
    html = HTML_PATH.read_text()
    for label in (
        "Durable Order Intent", "OMS / Broker", "Normalized Fill",
        "Reconciliation", "Position Manager", "EventStore", "Canonical Projection", "WebSocket / UI",
    ):
        assert label in html
    assert "exact Fabio parity" not in html.lower()
