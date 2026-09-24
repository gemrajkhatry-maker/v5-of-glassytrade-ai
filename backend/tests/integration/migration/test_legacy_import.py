import hashlib
import sqlite3

from backend.scripts.migrate_legacy_database import migrate_database
from backend.scripts.verify_migration import verify_migration


def legacy_database(path):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE positions (contract_id TEXT PRIMARY KEY, quantity INTEGER)")
    connection.execute("INSERT INTO positions VALUES ('NIFTY', 10)")
    connection.commit()
    connection.close()


def test_migration_never_mutates_source(tmp_path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "target.db"
    legacy_database(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    manifest = migrate_database(source, target, "test-release")

    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert manifest.release_id == "test-release"
    assert verify_migration(source, target).verified is True


def test_migration_refuses_source_target_identity(tmp_path):
    source = tmp_path / "legacy.db"
    legacy_database(source)
    try:
        migrate_database(source, source, "test-release")
    except ValueError as exc:
        assert "different" in str(exc)
    else:
        raise AssertionError("migration should reject source == target")
