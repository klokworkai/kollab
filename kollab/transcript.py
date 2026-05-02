from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class TranscriptLog:
    def __init__(self, session_id: str, sessions_dir: Path) -> None:
        sessions_dir.mkdir(parents=True, exist_ok=True)
        self._path = sessions_dir / f"{session_id}.jsonl"
        self._file = self._path.open("a", encoding="utf-8")
        self._session_id = session_id

    def append(self, event: dict) -> None:
        event.setdefault("ts", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") +
                         f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z")
        event.setdefault("session_id", self._session_id)
        self._file.write(json.dumps(event) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    # context manager support
    def __enter__(self) -> TranscriptLog:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
