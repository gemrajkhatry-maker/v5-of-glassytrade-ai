import sqlite3

from backend.scripts.backup_restore_drill import restore_backup, semantic_projection_hash


def test_restore_rebuilds_identical_projection(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE projection (id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO projection(value) VALUES ('same')")
    connection.commit()
    connection.close()
    restored = tmp_path / "restored.db"

    restore_backup(source, restored)

    assert semantic_projection_hash(source) == semantic_projection_hash(restored)
