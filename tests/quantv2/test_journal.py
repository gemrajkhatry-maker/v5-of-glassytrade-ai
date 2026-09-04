from quantv2.journal import Journal
from quantv2.types import Decision

def test_journal_roundtrip(tmp_path):
    j = Journal(str(tmp_path / "j.jsonl"))
    j.log_decision("X", Decision(False, "NO_EDGE"))
    j.log_decision("X", Decision(True, "TRIPLE_A"))
    lines = j.lines()
    assert len(lines) == 2 and '"TRIPLE_A"' in lines[1] and '"NO_EDGE"' in lines[0]
