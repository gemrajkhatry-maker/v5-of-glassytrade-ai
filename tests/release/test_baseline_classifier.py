import subprocess
from pathlib import Path

import pytest

from scripts.capture_test_baseline import (
    CLASSIFICATIONS,
    BaselineRecord,
    capture_command,
    classify,
    parse_pytest_output,
    validate_records,
)


def test_parse_pytest_output_records_failures_skips_and_deselections():
    records = parse_pytest_output(
        output=(
            "FAILED tests/quant/test_a.py::test_risk - assertion\n"
            "SKIPPED [1] tests/quant/test_b.py:4: fixture unavailable\n"
            "DESELECTED [1] tests/quant/test_c.py::test_live\n"
            "1 failed, 1 passed, 1 skipped, 1 deselected\n"
        ),
        surface="quant",
        command="pytest tests/quant",
        commit_sha="abc123",
        classification_map={
            "tests/quant/test_a.py::test_risk": "SAFETY_INVARIANT",
            "tests/quant/test_b.py:4": "LEGACY_BEHAVIOR_TO_PRESERVE",
            "tests/quant/test_c.py::test_live": "SAFETY_INVARIANT",
        },
        evidence_path="evidence/quant.txt",
    )

    assert [record.outcome for record in records] == [
        "failed",
        "skipped",
        "deselected",
    ]
    assert all(record.classification in CLASSIFICATIONS for record in records)


def test_classification_fails_closed_for_unclassified_non_passed_result():
    with pytest.raises(ValueError, match="classification"):
        classify("failed", "tests/quant/test_unknown.py::test_case", {})


def test_validate_records_rejects_ambiguous_classification():
    record = BaselineRecord(
        test_id="tests/quant/test_case.py::test_x",
        surface="quant",
        command="pytest",
        commit_sha="abc123",
        outcome="failed",
        classification="SAFETY_INVARIANT",
        safety_domain="risk",
        owner="quant",
        disposition="investigate",
        target_wave="6",
        evidence_path="evidence.txt",
    )
    validate_records([record])
    object.__setattr__(record, "classification", None)
    with pytest.raises(ValueError, match="classification"):
        validate_records([record])


def test_capture_command_forces_hermetic_child_environment(tmp_path):
    seen = {}

    def runner(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    capture_command(
        surface="quant",
        command=("python", "-m", "pytest", "tests/"),
        commit_sha="abc123",
        classification_map={},
        evidence_path=str(tmp_path / "hermetic.txt"),
        timeout_seconds=1.0,
        cwd=Path("/tmp/baseline-capture"),
        runner=runner,
    )

    assert seen["env"]["GLASSYTRADE_HERMETIC"] == "1"
    assert seen["env"]["GLASSYTRADE_ENV"] == "paper"
    assert seen["cwd"] == Path("/tmp/baseline-capture")


def test_capture_command_records_timeout_without_requiring_a_runner(tmp_path):
    records = capture_command(
        surface="quant",
        command=("python", "-c", "sleep"),
        commit_sha="abc123",
        classification_map={},
        evidence_path=str(tmp_path / "timeout.txt"),
        timeout_seconds=0.01,
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd=("python", "-c", "sleep"), timeout=0.01)
        ),
    )

    assert len(records) == 1
    assert records[0].outcome == "timeout"
    assert records[0].classification == "SAFETY_INVARIANT"
