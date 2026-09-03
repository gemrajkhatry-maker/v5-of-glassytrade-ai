import json
import os
import tempfile


class Journal:
    """Append-only JSONL event journal with size-capped rotation.

    ``fsync=True`` (default) flushes the OS buffer on every append so a
    crash loses at most the record being written — required for any
    reconciliation use. Set ``fsync=False`` for high-volume replay-only
    journals where throughput matters more than crash durability.

    When the active file exceeds ``max_size`` bytes the current file is
    archived to ``<path>.<n>`` and a fresh file is opened, so disk usage
    stays bounded. ``replay()`` reads archived segments in order followed by
    the active file.
    """

    def __init__(
        self,
        path: str | None = None,
        fsync: bool = True,
        max_size: int = 100 * 1024 * 1024,
    ) -> None:
        if path is None:
            fd, path = tempfile.mkstemp(prefix="journal-", suffix=".jsonl")
            os.close(fd)
        self._path = path
        self._fsync = fsync
        self.max_size = max_size
        self._rotation_index = 0
        self._file = open(path, "a", encoding="utf-8")
        self.consecutive_failures = 0

    def _rotate(self) -> None:
        """Archive the current file and start a fresh one."""
        self._file.close()
        self._rotation_index += 1
        archive = f"{self._path}.{self._rotation_index}"
        if os.path.exists(archive):
            os.remove(archive)
        os.rename(self._path, archive)
        self._file = open(self._path, "a", encoding="utf-8")

    def append(self, record: dict) -> None:
        try:
            if self.max_size and os.path.getsize(self._path) > self.max_size:
                self._rotate()
            self._file.write(json.dumps(record) + "\n")
            self._file.flush()
            if self._fsync:
                os.fsync(self._file.fileno())
            self.consecutive_failures = 0
        except Exception:
            self.consecutive_failures += 1
            raise

    def _segment_paths(self) -> list[str]:
        """Archived segments (oldest first) followed by the active file."""
        segments = [
            f"{self._path}.{i}"
            for i in range(1, self._rotation_index + 1)
            if os.path.exists(f"{self._path}.{i}")
        ]
        return segments + [self._path]

    def replay(self) -> list[dict]:
        rows = []
        for path in self._segment_paths():
            with open(path, encoding="utf-8") as f:
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
