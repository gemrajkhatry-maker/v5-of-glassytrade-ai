#!/usr/bin/env python3
"""Resolve the v6.0 refactoring execution graph into a parallel schedule.

Reads ``docs/architecture/2026-09-11-v6-execution-graph.json`` and reports:

* **waves** — topological layers respecting ``blocked_by`` edges, so every node
  in a wave can run concurrently;
* **collisions** — nodes inside one wave that share a file path and therefore
  must be serialized regardless of the graph edges;
* **batches** — a wave packed into groups of at most ``--cap`` agents, ordered by
  risk, so an unlimited fan-out becomes a schedulable team size;
* **critical path** — the effort-weighted longest chain, i.e. what actually
  determines the delivery date;
* **worktree plan** — the ``git worktree add`` commands for a chosen wave;
* **mermaid** — the diagram embedded in the plan doc, generated from the graph so
  it cannot drift from the edges.

Stdlib only, read-only: this never mutates the repository.

Usage:
    python3 scripts/plan_waves.py
    python3 scripts/plan_waves.py --wave 1
    python3 scripts/plan_waves.py --worktrees 1
    python3 scripts/plan_waves.py --json
    python3 scripts/plan_waves.py --mermaid
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

GRAPH_PATH = Path("docs/architecture/2026-09-11-v6-execution-graph.json")
DEFAULT_CAP = 4

# Lower rank starts first: money safety, then security, then correctness.
RISK_RANK = {
    "money-path": 0,
    "security": 1,
    "correctness": 2,
    "perf": 3,
    "structural": 4,
    "verification": 5,
    "legal": 6,
    "docs": 7,
}


class GraphError(Exception):
    """Raised when the graph is malformed; a broken graph must not schedule work."""


def load_graph(path: Path) -> dict:
    if not path.exists():
        raise GraphError(f"graph not found: {path}")
    with path.open(encoding="utf-8") as handle:
        graph = json.load(handle)

    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise GraphError("graph has no nodes")

    seen: set[str] = set()
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            raise GraphError(f"node without id: {node!r}")
        if node_id in seen:
            raise GraphError(f"duplicate node id: {node_id}")
        seen.add(node_id)

    for node in nodes:
        for dep in node.get("blocked_by", []):
            if dep not in seen:
                raise GraphError(f"{node['id']} blocked_by unknown node {dep}")

    return graph


def assign_waves(nodes: list[dict]) -> dict[str, int]:
    """Longest-path layering. Raises on a dependency cycle."""
    by_id = {node["id"]: node for node in nodes}
    waves: dict[str, int] = {}
    visiting: set[str] = set()

    def resolve(node_id: str) -> int:
        if node_id in waves:
            return waves[node_id]
        if node_id in visiting:
            raise GraphError(f"dependency cycle through {node_id}")
        visiting.add(node_id)
        deps = by_id[node_id].get("blocked_by", [])
        wave = 0 if not deps else 1 + max(resolve(dep) for dep in deps)
        visiting.discard(node_id)
        waves[node_id] = wave
        return wave

    for node_id in by_id:
        resolve(node_id)
    return waves


def find_collisions(nodes: list[dict], waves: dict[str, int]) -> list[tuple[str, str, str]]:
    """Return (file, node_a, node_b) for same-wave nodes sharing a path prefix."""
    by_wave: dict[int, list[dict]] = {}
    for node in nodes:
        by_wave.setdefault(waves[node["id"]], []).append(node)

    collisions: list[tuple[str, str, str]] = []
    for wave, members in sorted(by_wave.items()):
        for i, left in enumerate(members):
            for right in members[i + 1:]:
                for file_left in left.get("files", []):
                    for file_right in right.get("files", []):
                        if _paths_overlap(file_left, file_right):
                            collisions.append((file_left, left["id"], right["id"]))
    return collisions


def _paths_overlap(a: str, b: str) -> bool:
    """True when two footprint entries could touch the same file.

    Directory entries (trailing '/') overlap anything nested beneath them.
    """
    if a == b:
        return True
    if a.endswith("/") and b.startswith(a):
        return True
    if b.endswith("/") and a.startswith(b):
        return True
    return False


def critical_path(nodes: list[dict]) -> tuple[list[str], float]:
    by_id = {node["id"]: node for node in nodes}
    memo: dict[str, tuple[list[str], float]] = {}

    def longest(node_id: str) -> tuple[list[str], float]:
        if node_id in memo:
            return memo[node_id]
        node = by_id[node_id]
        best: tuple[list[str], float] = ([], 0.0)
        for dep in node.get("blocked_by", []):
            path, weight = longest(dep)
            if weight > best[1]:
                best = (path, weight)
        result = (best[0] + [node_id], best[1] + float(node.get("effort", 0)))
        memo[node_id] = result
        return result

    return max((longest(node_id) for node_id in by_id), key=lambda pair: pair[1])


def pack_batches(members: list[dict], cap: int) -> list[list[dict]]:
    """Greedily pack a wave into batches of <= cap, never mixing colliding nodes."""
    ordered = sorted(
        members,
        key=lambda n: (RISK_RANK.get(n.get("risk", "docs"), 99), -float(n.get("effort", 0)), n["id"]),
    )
    batches: list[list[dict]] = []
    for node in ordered:
        placed = False
        for batch in batches:
            if len(batch) >= cap:
                continue
            if any(_nodes_collide(node, other) for other in batch):
                continue
            batch.append(node)
            placed = True
            break
        if not placed:
            batches.append([node])
    return batches


def _nodes_collide(left: dict, right: dict) -> bool:
    return any(
        _paths_overlap(a, b)
        for a in left.get("files", [])
        for b in right.get("files", [])
    )


def render(graph: dict, cap: int = DEFAULT_CAP) -> str:
    nodes = graph["nodes"]
    waves = assign_waves(nodes)
    collisions = find_collisions(nodes, waves)
    path, effort = critical_path(nodes)
    by_id = {node["id"]: node for node in nodes}

    lines: list[str] = []
    lines.append(f"nodes: {len(nodes)}   waves: {max(waves.values()) + 1}   "
                 f"critical path: {effort:g} agent-days")
    lines.append("")

    for wave in sorted(set(waves.values())):
        members = sorted((n for n in nodes if waves[n["id"]] == wave), key=lambda n: n["id"])
        total = sum(float(n.get("effort", 0)) for n in members)
        batches = pack_batches(members, cap)
        lines.append(
            f"## Wave {wave} — {len(members)} node(s), {total:g} agent-days, "
            f"{len(batches)} batch(es) at cap={cap}"
        )
        for index, batch in enumerate(batches, start=1):
            lines.append(f"  -- batch {wave}.{index} ({len(batch)} agents) --")
            for node in batch:
                deps = ",".join(node.get("blocked_by", [])) or "-"
                lines.append(
                    f"  {node['id']:<6} [{node['squad']:<6}] {node['effort']:>4}g  "
                    f"{node['type']:<8} {node['risk']:<10} deps={deps:<12} {node['title']}"
                )
        lines.append("")

    lines.append("## File collisions inside a wave (must be serialized)")
    if not collisions:
        lines.append("  none")
    else:
        for file, left, right in collisions:
            lines.append(f"  {left} <-> {right}  ({file})")
    lines.append("")

    lines.append("## Critical path (effort-weighted)")
    lines.append("  " + " -> ".join(path))
    lines.append("")
    lines.append("## Critical path detail")
    for node_id in path:
        node = by_id[node_id]
        lines.append(f"  {node_id:<6} {node['effort']:>4}g  {node['title']}")
    return "\n".join(lines)


def worktree_commands(graph: dict, wave: int) -> str:
    nodes = graph["nodes"]
    waves = assign_waves(nodes)
    members = sorted((n for n in nodes if waves[n["id"]] == wave), key=lambda n: n["id"])
    if not members:
        return f"# no nodes in wave {wave}"

    root = graph.get("conventions", {}).get("worktree_root", ".worktrees")
    lines = [f"# wave {wave}: {len(members)} parallel agent(s)",
             "git -C . fetch --all --prune   # optional: start from a fresh base", ""]
    for node in members:
        slug = node["id"].lower()
        lines.append(
            f"git worktree add {root}/{slug} -b agent/{slug} "
            f"# {node['squad']}: {node['title']}"
        )
    lines.append("")
    lines.append("# merge order: land nodes in the order listed in `--wave`, "
                 "re-running tests/architecture after each")
    lines.append("# cleanup: git worktree remove " + f"{root}/<id>  &&  git branch -d agent/<id>")
    return "\n".join(lines)


def mermaid(graph: dict) -> str:
    """Render the graph as a mermaid flowchart, grouped by resolved wave."""
    nodes = graph["nodes"]
    waves = assign_waves(nodes)
    lines = ["flowchart TB"]
    for wave in sorted(set(waves.values())):
        members = [n for n in nodes if waves[n["id"]] == wave]
        lines.append(f'  subgraph W{wave}["Wave {wave}"]')
        for node in sorted(members, key=lambda n: n["id"]):
            label = node["title"].replace('"', "'").replace("—", "-")
            lines.append(f'    {node["id"]}["{node["id"]}: {label}"]')
        lines.append("  end")
    for node in nodes:
        for dep in node.get("blocked_by", []):
            lines.append(f'  {dep} --> {node["id"]}')
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", default=str(GRAPH_PATH), help="path to the execution graph")
    parser.add_argument("--wave", type=int, help="print only the nodes in this wave")
    parser.add_argument("--worktrees", type=int, metavar="WAVE",
                        help="print git worktree provisioning commands for a wave")
    parser.add_argument("--json", action="store_true", help="emit machine-readable schedule")
    parser.add_argument("--mermaid", action="store_true",
                        help="emit the mermaid diagram embedded in the plan doc")
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP,
                        help=f"max parallel agents per batch (default {DEFAULT_CAP})")
    args = parser.parse_args(argv)

    try:
        graph = load_graph(Path(args.graph))
    except GraphError as exc:
        print(f"graph error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.worktrees is not None:
            print(worktree_commands(graph, args.worktrees))
            return 0

        if args.mermaid:
            print(mermaid(graph))
            return 0

        if args.json:
            nodes = graph["nodes"]
            waves = assign_waves(nodes)
            path, effort = critical_path(nodes)
            print(json.dumps({
                "waves": {str(w): sorted(n["id"] for n in nodes if waves[n["id"]] == w)
                          for w in sorted(set(waves.values()))},
                "batches": {
                    str(w): [[n["id"] for n in batch] for batch in pack_batches(
                        [n for n in nodes if waves[n["id"]] == w], args.cap)]
                    for w in sorted(set(waves.values()))
                },
                "cap": args.cap,
                "critical_path": path,
                "critical_path_effort": effort,
                "collisions": [
                    {"file": f, "a": a, "b": b} for f, a, b in find_collisions(nodes, waves)
                ],
            }, indent=2))
            return 0

        if args.wave is not None:
            nodes = graph["nodes"]
            waves = assign_waves(nodes)
            members = [n for n in nodes if waves[n["id"]] == args.wave]
            if not members:
                print(f"wave {args.wave} is empty", file=sys.stderr)
                return 1
            for node in sorted(members, key=lambda n: n["id"]):
                print(f"{node['id']:<6} {node['squad']:<6} {node['effort']:>4}g  {node['title']}")
                for file in node.get("files", []):
                    print(f"        {file}")
            return 0

        print(render(graph, cap=args.cap))
        return 0
    except GraphError as exc:
        print(f"graph error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
