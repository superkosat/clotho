"""Persistent mapping of WhatsApp JIDs to Clotho chat IDs."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SESSIONS_PATH = Path.home() / ".clotho" / "whatsapp" / "sessions.json"


class SessionMap:
    """Thread-safe-ish (single-process) JID → chat_id store backed by JSON."""

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

    def get(self, jid: str) -> str | None:
        return self._data.get(jid)

    def set(self, jid: str, chat_id: str) -> None:
        self._data[jid] = chat_id
        self._save()

    def remove(self, jid: str) -> None:
        if jid in self._data:
            del self._data[jid]
            self._save()

    def all(self) -> dict[str, str]:
        return dict(self._data)
