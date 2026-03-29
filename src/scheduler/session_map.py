"""Persistent mapping of job names to Clotho chat IDs."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SESSIONS_PATH = Path.home() / ".clotho" / "scheduler" / "sessions.json"


class SessionMap:
    """Job name → chat_id store backed by a JSON file.

    Each job gets its own persistent chat session, keyed on job name.
    This keeps scheduled job context separate from interactive sessions.
    """

    def __init__(self, path: Path = DEFAULT_SESSIONS_PATH) -> None:
        self._path = path
        self._data: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if self._path.is_file():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, chat_id: str) -> None:
        self._data[key] = chat_id
        self._save()

    def remove(self, key: str) -> None:
        if key in self._data:
            del self._data[key]
            self._save()

    def all(self) -> dict[str, str]:
        return dict(self._data)
