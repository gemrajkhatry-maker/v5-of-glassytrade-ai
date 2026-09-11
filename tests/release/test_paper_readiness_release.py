"""Release contract for paper readiness, not live execution."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "PAPER_READINESS_RELEASE_VALIDATION.md"


def test_release_validation_doc_exists_and_explicitly_blocks_live_execution():
    text = DOC.read_text(encoding="utf-8")
    assert "PAPER READY" in text
    assert "LIVE: NO-GO" in text
    assert "paper" in text.lower()
    assert "broker execution" in text.lower()


def test_release_validation_names_all_required_gates():
    text = DOC.read_text(encoding="utf-8")
    for required in ("architecture", "replay parity", "paper protocol", "readiness"):
        assert required in text.lower(), required
    assert "tests/architecture" in text
    assert "tests/quant/test_golden_replay.py" in text
    assert "tests/system/test_paper_protocol.py" in text


def test_release_validation_protects_execution_and_symbol_mapping_boundaries():
    text = DOC.read_text(encoding="utf-8")
    assert "brokers/broker/dhan/infrastructure/symbol_mapper.py" in text
    assert "NO-GO" in text
    assert "must not change" in text.lower()
