"""PHASE 11 — dead / unreachable code detection via AST walk (no new deps).

Run:  PYTHONPATH=backend:. .venv/bin/python runtime_audit/audit/dead_code_scan.py

Outputs:
  (a) functions/methods/classes never referenced by name anywhere else in the
      repo (.py/.ts/.tsx textual search, definition excluded)
  (b) `if False` / `while False` unreachable branches
  (c) modules with zero importers
Writes: runtime_audit/out/dead_code_report.txt
"""

from __future__ import annotations

import ast
import os
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ["quant", "backend/app", "brokers", "routers", "shared"]
REF_EXTS = {".py", ".ts", ".tsx"}
KNOWN_DEAD = [
    "quant/amt/market/vwap_bands.py",
    "quant/contracts/ports/llm_inference.py",
    "quant/advisory",
    "quant/compression_box.py",
    "quant/range_bars.py",
    "brokers/broker/paper/broker.py",
    "brokers/broker/market_info.py",
    "backend/app/infrastructure/metrics.py",
    "routers/metrics.py",
]

# Test files legitimately reference production names; keep them as references
# but tag them so the report can separate "test-only" from "fully dead".
TEST_MARKERS = ("/tests/", "test_", "/audit/")


def iter_py_files() -> list[Path]:
    files = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in str(p):
                continue
            files.append(p)
    return files


def collect_reference_corpus(files: list[Path]) -> dict[str, list[str]]:
    """name -> list of files mentioning it (raw word-boundary text match)."""
    corpus: dict[str, list[str]] = defaultdict(list)
    skip_parts = {".git", "node_modules", ".venv", "__pycache__", "graphify-out",
                  "amt_dataset", "models", "dist", ".opencode"}
    ref_files = [
        p for p in ROOT.rglob("*")
        if p.suffix in REF_EXTS and p.is_file()
        and not (set(p.parts) & skip_parts)
    ]
    for rf in ref_files:
        try:
            text = rf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", text)):
            corpus[name].append(str(rf.relative_to(ROOT)))
    return corpus


def defined_names(tree: ast.AST) -> list[tuple[str, int, str]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("__") and node.name.endswith("__"):
                continue  # dunders are protocol hooks
            kind = "class" if isinstance(node, ast.ClassDef) else "func"
            out.append((node.name, node.lineno, kind))
    return out


def module_import_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    # backend/app/... is imported as backend.app... when run from repo root,
    # or app.... when run from backend/. Record both candidates.
    cands = {".".join(parts)}
    if parts[0] == "backend":
        cands.add(".".join(parts[1:]))
    return " | ".join(sorted(cands))


def main() -> None:
    py_files = iter_py_files()
    corpus = collect_reference_corpus(py_files)

    unreferenced: list[tuple[str, str, int, str, list[str]]] = []  # file,name,line,kind,refs
    unreachable_branches: list[tuple[str, int]] = []
    importer_map: dict[str, set[str]] = defaultdict(set)  # module -> importing files

    # Pre-scan all files once for imports + raw text.
    file_texts: dict[Path, str] = {}
    for p in py_files:
        try:
            file_texts[p] = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            file_texts[p] = ""

    for p, text in file_texts.items():
        mod = str(p.relative_to(ROOT).with_suffix("")).replace("/", ".")
        mod_short = mod.replace("backend.app.", "app.")
        # precise import detection
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        importer_map[a.name].add(str(p.relative_to(ROOT)))
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        importer_map[node.module].add(
                            str(p.relative_to(ROOT))
                        )
        for m in re.findall(
            r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", text, re.M
        ):
            name = m[0] or m[1]
            importer_map[name].add(str(p.relative_to(ROOT)))

    for p in py_files:
        rel = str(p.relative_to(ROOT))
        text = file_texts[p]
        # (b) statically-unreachable branches
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if re.match(r"^if\s+False\b", s) or re.match(r"^while\s+False\b", s):
                unreachable_branches.append((rel, i))
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for name, lineno, kind in defined_names(tree):
            referencing_files = [f for f in corpus.get(name, []) if f != rel]
            if not referencing_files:
                unreferenced.append((rel, name, lineno, kind, []))
                continue
            non_test = [f for f in referencing_files if not any(mk in f for mk in TEST_MARKERS)]
            if not non_test:
                unreferenced.append((rel, name, lineno, kind, referencing_files[:5]))

    lines_out = []
    lines_out.append("=" * 78)
    lines_out.append("DEAD / UNREACHABLE CODE REPORT — generated by dead_code_scan.py")
    lines_out.append("=" * 78)

    lines_out.append("\n## (c) Known-dead list — zero-importer confirmation (today)\n")
    # Precompute import-statement text per file for the dynamic-import fallback.
    import_text: dict[str, str] = {}
    for q, t2 in file_texts.items():
        sq = str(q)
        import_text[sq] = "\n".join(
            ln for ln in t2.splitlines()
            if re.match(r"\s*(from\s+[\w.]+\s+import|import\s+[\w.])", ln)
        )
    for target in KNOWN_DEAD:
        tpath = ROOT / target
        if tpath.is_dir():
            mods = [str(m.relative_to(ROOT)).replace("/", ".")[:-3]
                    for m in tpath.rglob("*.py") if "__pycache__" not in str(m)]
            files_of_interest = {
                str(m.relative_to(ROOT)): m
                for m in tpath.rglob("*.py") if "__pycache__" not in str(m)
            }
        else:
            mods = [target.replace("/", ".")[:-3]]
            files_of_interest = {target: tpath}
        findings = []
        for mod in mods:
            short = mod.replace("backend.app.", "app.")
            importers = []
            for key, who in importer_map.items():
                if key == mod or key == short or key.startswith(mod + ".") or key.startswith(short + "."):
                    importers.extend(who)
            # also plain-text fallback (dynamic imports): any import line
            # mentioning any leaf module name of this package/file.
            if not importers:
                leaves = {m.split(".")[-1] for m in mods}
                for sq, itext in import_text.items():
                    if sq in files_of_interest:
                        continue
                    if any(re.search(rf"\b{re.escape(leaf)}\b", itext) for leaf in leaves):
                        importers.append(sq)
            status = ("ZERO IMPORTERS — CONFIRMED DEAD TODAY"
                      if not importers else f"IMPORTED BY: {sorted(set(importers))[:6]}")
            findings.append(f"  {mod}: {status}")
        lines_out.extend(findings)
        lines_out.append("")

    lines_out.append("\n## (a) Functions/methods/classes never referenced outside their own file\n")
    lines_out.append("(tagged TEST-ONLY when referenced solely from tests/audit code)\n")
    count_total = len(unreferenced)
    for rel, name, lineno, kind, refs in sorted(unreferenced):
        tag = "TEST-ONLY" if refs else "FULLY-DEAD"
        lines_out.append(f"  [{tag}] {rel}:{lineno} {kind} {name}")
    lines_out.append(f"\n  total flagged: {count_total}")

    lines_out.append("\n## (b) Statically unreachable branches (`if False` / `while False`)\n")
    if not unreachable_branches:
        lines_out.append("  none found")
    for rel, lineno in unreachable_branches:
        lines_out.append(f"  {rel}:{lineno}")

    report = "\n".join(lines_out)
    out = ROOT / "runtime_audit/out/dead_code_report.txt"
    out.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
