from pathlib import Path

from scripts.check_retirement import check_retirement


def test_retirement_requires_explicit_cutover_evidence():
    report = check_retirement(Path("."), evidence_verified=False)
    assert report.ready is False
    assert "cutover_evidence_missing" in report.blockers
