"""Capture and classify the repository's offline test baseline."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

CLASSIFICATIONS = frozenset(
    {
        "SAFETY_INVARIANT",
        "LEGACY_BEHAVIOR_TO_PRESERVE",
        "INTENTIONAL_REWRITE_CHANGE",
        "OBSOLETE_IMPLEMENTATION_TEST",
    }
)
_NON_PASSED = frozenset({"failed", "skipped", "deselected", "timeout"})
_OUTCOME_PATTERNS = {
    "failed": re.compile(r"^FAILED\s+(?P<test_id>\S+)(?:\s+-\s+.*)?$"),
    "skipped": re.compile(r"^SKIPPED(?:\s+\[\d+\])?\s+(?P<test_id>\S+)(?::\d+)?(?::\s+.*)?$"),
    "deselected": re.compile(r"^DESELECTED(?:\s+\[\d+\])?\s+(?P<test_id>\S+)(?::\d+)?(?::\s+.*)?$"),
}


@dataclass(frozen=True)
class BaselineRecord:
    test_id: str
    surface: str
    command: str
    commit_sha: str
    outcome: str
    classification: str | None
    safety_domain: str
    owner: str
    disposition: str
    target_wave: str
    evidence_path: str


def classify(
    outcome: str,
    test_id: str,
    classification_map: Mapping[str, str],
) -> str | None:
    if outcome not in _NON_PASSED:
        return None
    classification = classification_map.get(test_id)
    if classification not in CLASSIFICATIONS:
        raise ValueError(
            f"missing or invalid classification for {outcome} test {test_id!r}"
        )
    return classification


def _record(
    *,
    test_id: str,
    surface: str,
    command: str,
    commit_sha: str,
    outcome: str,
    classification_map: Mapping[str, str],
    evidence_path: str,
) -> BaselineRecord:
    classification = classify(outcome, test_id, classification_map)
    domain = "runtime" if outcome == "timeout" else "test"
    return BaselineRecord(
        test_id=test_id,
        surface=surface,
        command=command,
        commit_sha=commit_sha,
        outcome=outcome,
        classification=classification,
        safety_domain=domain,
        owner=surface,
        disposition="triage",
        target_wave="0",
        evidence_path=evidence_path,
    )


def parse_pytest_output(
    *,
    output: str,
    surface: str,
    command: str,
    commit_sha: str,
    classification_map: Mapping[str, str],
    evidence_path: str,
) -> list[BaselineRecord]:
    records: list[BaselineRecord] = []
    for line in output.splitlines():
        for outcome, pattern in _OUTCOME_PATTERNS.items():
            match = pattern.match(line.strip())
            if match:
                records.append(
                    _record(
                        test_id=match.group("test_id"),
                        surface=surface,
                        command=command,
                        commit_sha=commit_sha,
                        outcome=outcome,
                        classification_map=classification_map,
                        evidence_path=evidence_path,
                    )
                )
                break
    return records


def validate_records(records: Sequence[BaselineRecord]) -> None:
    for record in records:
        if record.outcome in _NON_PASSED and record.classification not in CLASSIFICATIONS:
            raise ValueError(
                f"invalid classification for {record.outcome} test {record.test_id!r}"
            )
        if record.outcome not in _NON_PASSED | {"passed"}:
            raise ValueError(f"unsupported outcome {record.outcome!r}")


def capture_command(
    *,
    surface: str,
    command: Sequence[str],
    commit_sha: str,
    classification_map: Mapping[str, str],
    evidence_path: str,
    timeout_seconds: float,
    cwd: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[BaselineRecord]:
    child_env = os.environ.copy()
    for key in tuple(child_env):
        if key.startswith(("DHAN_", "LIVE_")):
            child_env.pop(key, None)
    child_env["GLASSYTRADE_HERMETIC"] = "1"
    child_env["GLASSYTRADE_ENV"] = "paper"

    try:
        completed = runner(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=child_env,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        evidence = Path(evidence_path)
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(output, encoding="utf-8")
        return [
            _record(
                test_id=f"{surface}:command-timeout",
                surface=surface,
                command=" ".join(command),
                commit_sha=commit_sha,
                outcome="timeout",
                classification_map={
                    f"{surface}:command-timeout": "SAFETY_INVARIANT"
                },
                evidence_path=evidence_path,
            )
        ]

    evidence = Path(evidence_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        (completed.stdout or "") + (completed.stderr or ""), encoding="utf-8"
    )
    return parse_pytest_output(
        output=(completed.stdout or "") + (completed.stderr or ""),
        surface=surface,
        command=" ".join(command),
        commit_sha=commit_sha,
        classification_map=classification_map,
        evidence_path=evidence_path,
    )


def _default_commands(root: Path) -> dict[str, tuple[Sequence[str], Path]]:
    python = sys.executable
    return {
        "backend": (
            (python, "-m", "pytest", "tests/", "-q", "--maxfail=1"),
            root / "backend",
        ),
        "quant": (
            (
                python,
                "-m",
                "pytest",
                "tests/",
                "-q",
                "--maxfail=1",
                "--ignore=tests/e2e",
            ),
            root,
        ),
        "broker": (
            (python, "-m", "pytest", "-q"),
            root / "brokers",
        ),
        "frontend": (("npm", "test", "--", "--run"), root / "frontend"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--classification-map",
        type=Path,
        required=True,
        help="JSON object mapping test IDs to one approved classification",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    commit_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    classification_map = json.loads(args.classification_map.read_text(encoding="utf-8"))
    if not isinstance(classification_map, dict):
        parser.error("classification map must be a JSON object")

    records: list[BaselineRecord] = []
    for surface, (command, cwd) in _default_commands(root).items():
        records.extend(
            capture_command(
                surface=surface,
                command=command,
                commit_sha=commit_sha,
                classification_map=classification_map,
                evidence_path=str(args.evidence_dir / f"{surface}.txt"),
                timeout_seconds=args.timeout_seconds,
                cwd=cwd,
            )
        )
    validate_records(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps([asdict(record) for record in records], indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
