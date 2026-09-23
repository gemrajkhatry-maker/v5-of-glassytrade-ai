from quant.persistence import Journal


def test_append_and_replay(tmp_path):
    j = Journal(path=str(tmp_path / "journal.jsonl"))
    j.append({"type": "BarClosed", "symbol": "S", "time": "t1"})
    j.append({"type": "DecisionProduced", "symbol": "S", "time": "t2"})
    rows = j.replay()
    assert len(rows) == 2 and rows[0]["type"] == "BarClosed"


def test_append_only_no_overwrite(tmp_path):
    j = Journal(path=str(tmp_path / "j2.jsonl"))
    j.append({"a": 1})
    j2 = Journal(path=str(tmp_path / "j2.jsonl"))
    j2.append({"a": 2})
    assert len(j2.replay()) == 2   # append, not truncate


def test_default_path_is_temporary():
    j = Journal()
    j.append({"a": 1})
    assert len(j.replay()) == 1


def test_len_counts_records(tmp_path):
    j = Journal(path=str(tmp_path / "j3.jsonl"))
    j.append({"a": 1})
    j.append({"a": 2})
    assert len(j) == 2
