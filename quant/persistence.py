import json
import os
import tempfile


class Journal:
    """Append-only JSONL event journal.

    ``fsync=True`` (default) flushes the OS buffer on every append so a
    crash loses at most the record being written — required for any
    reconciliation use. Set ``fsync=False`` for high-volume replay-only
    journals where throughput matters more than crash durability.
    """

    def __init__(self, path: str | None = None, fsync: bool = True) -> None:
        if path is None:
            fd, path = tempfile.mkstemp(prefix="journal-", suffix=".jsonl")
            os.close(fd)
        self._path = path
        self._fsync = fsync
        self._file = open(path, "a", encoding="utf-8")

    def append(self, record: dict) -> None:
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()
        if self._fsync:
            os.fsync(self._file.fileno())

    def replay(self) -> list[dict]:
        rows = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows

    def __len__(self) -> int:
        return len(self.replay())

    def close(self) -> None:
        try:
            self._file.close()
        except Exception:
            pass
