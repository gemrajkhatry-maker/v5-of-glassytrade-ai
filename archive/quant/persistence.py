import json
import tempfile


class Journal:
    def __init__(self, path: str | None = None) -> None:
        if path is None:
            fd, path = tempfile.mkstemp(prefix="journal-", suffix=".jsonl")
            import os
            os.close(fd)
        self._path = path
        self._file = open(path, "a", encoding="utf-8")

    def append(self, record: dict) -> None:
        # ``default=float`` keeps the append-only JSONL replayer working now that
        # signals carry Decimal prices (the canonical domain Signal).
        self._file.write(json.dumps(record, default=float) + "\n")
        self._file.flush()

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
