#!/usr/bin/env python3
"""
triage_parallel_work.py — next parallel scope from the v6 execution graph.

Answers, from the machine-readable graph:
- which nodes are still open
- which ones have no remaining blocked_by after merges
- which set can run in parallel with no file collisions
- which files each node owns, so two agents can never step on the same path

Does NOT mutate the graph. Reads it only.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

GRAPH = Path("docs/architecture/2026-09-11-v6-execution-graph.json")
MERGED_MARKER = Path("MERGED_NODES.md")

RISK_ORDER = [
    "money-path",
    "security",
    "correctness",
    "perf",
    "structural",
    "verification",
    "legal",
    "docs",
    None,
]


def load() -> dict:
    return json.loads(GRAPH.read_text())


def risk_index(node: dict) -> int:
    r = node.get("risk")
    if r in RISK_ORDER:
        return RISK_ORDER.index(r)
    return 99


def blocked_by_ids(node: dict, edges: list[dict]) -> list[str]:
    return [e["from"] for e in edges if e.get("kind") == "dependency" and e.get("to") == node["id"]]


def topological_waves(nodes: list[dict], edges: list[dict]) -> list[list[str]]:
    in_degree: dict[str, int] = {n["id"]: 0 for n in nodes}
    downstream: dict[str, list[str]] = defaultdict(list)

    for e in edges:
        f = e.get("from")
        t = e.get("to")
        if f and t and e.get("kind") == "dependency":
            in_degree[t] = in_degree.get(t, 0) + 1
            downstream[f].append(t)

    remaining = {n["id"] for n in nodes}
    waves: list[list[str]] = []

    while remaining:
        ready = [n for n in remaining if in_degree.get(n, 0) == 0]
        if not ready:
            break
        ready.sort(key=lambda n: (risk_index(nodes_by_id[n]), n))
        waves.append(ready)
        for n in ready:
            remaining.remove(n)
            for t in downstream[n]:
                in_degree[t] = in_degree.get(t, 0) - 1

    return waves


def collision_free_wave(wave: list[str], nodes_by_id: dict[str, dict]) -> tuple[list[str], list[tuple[str, str, str]]]:
    owned: dict[str, list[str]] = defaultdict(list)
    for nid in wave:
        for f in nodes_by_id[nid].get("files", []):
            owned[f].append(nid)

    collisions: list[tuple[str, str, str]] = []
    for f, owners in owned.items():
        if len(owners) > 1:
            collisions.append((owners[0], owners[1], f))

    blocked_ids: set[str] = {a for a, _, _ in collisions} | {b for _, b, _ in collisions}
    ok = [nid for nid in wave if nid not in blocked_ids]
    return ok, collisions


def merged() -> set[str]:
    if not MERGED_MARKER.exists():
        return set()
    return {ln.strip() for ln in MERGED_MARKER.read_text().splitlines() if ln.strip()}


def main() -> None:
    global nodes_by_id
    data = load()
    nodes = data["nodes"]
    edges = data.get("edges", [])
    nodes_by_id = {n["id"]: n for n in nodes}

    print("graph:", GRAPH)
    print("nodes:", len(nodes), "edges:", len(edges))
    print()

    naive_waves = topological_waves(nodes, edges)
    print(f"naive dependency waves: {len(naive_waves)}")
    for i, w in enumerate(naive_waves):
        print(f"  wave {i}: {len(w)} nodes -> {w}")
    print()

    merged_ids = merged()
    print("merged markers:", sorted(merged_ids) or "none")
    print()

    open_nodes = [n for n in nodes if n["id"] not in merged_ids]
    available: list[str] = []
    for n in open_nodes:
        blockers = blocked_by_ids(n, edges)
        if all(b in merged_ids for b in blockers):
            available.append(n["id"])

    print(f"open nodes: {len(open_nodes)}  | immediately available (no unmerged blockers): {len(available)}")
    print("available:", sorted(available))
    print()

    available.sort(key=lambda nid: (risk_index(nodes_by_id[nid]), nid))
    ok, collisions = collision_free_wave(available, nodes_by_id)

    print(f"collision-free parallel set from available: {len(ok)}")
    for nid in ok:
        n = nodes_by_id[nid]
        print(f"  {nid:7s} risk={str(n.get('risk')):10s} phase={n.get('phase')} readiness={n.get('readiness')} files={n.get('files')}")
    print()

    if collisions:
        print("COLLISIONS (would block parallel run):")
        for a, b, f in collisions:
            print(f"  {a} vs {b} on {f}")
    else:
        print("no file collisions among the immediately available set")

    if not ok and collisions:
        print()
        print("action: pick one of the colliding files, split the node or wait.")
        sys.exit(2)


if __name__ == "__main__":
    main()
