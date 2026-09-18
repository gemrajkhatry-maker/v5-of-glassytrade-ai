from __future__ import annotations

import json
from html.parser import HTMLParser
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


class _DiagramParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = set()
        self.edges = set()
        self.dashed_edges = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-node-id" in attrs:
            self.nodes.add(attrs["data-node-id"])
        if "data-edge-from" in attrs and "data-edge-to" in attrs:
            edge = (attrs["data-edge-from"], attrs["data-edge-to"])
            self.edges.add(edge)
            if "dashed" in attrs.get("class", ""):
                self.dashed_edges.add(edge)


def test_gap_architecture_html_renders_json_nodes_and_edges():
    artifact = json.loads(JSON_PATH.read_text())
    parser = _DiagramParser()
    parser.feed(HTML_PATH.read_text())
    assert {node["id"] for node in artifact["nodes"]} <= parser.nodes
    required_edges = {(edge["from"], edge["to"]): edge for edge in artifact["edges"]}
    assert set(required_edges) <= parser.edges
    assert ("ctx", "narrative") in parser.dashed_edges
