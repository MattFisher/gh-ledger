"""On-disk cache of API responses, keyed by request."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ResponseCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    @staticmethod
    def key(method: str, url: str, body: str) -> str:
        return hashlib.sha256(f"{method}\n{url}\n{body}".encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self._root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Any | None:
        try:
            return json.loads(self._path(key).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None  # torn write from an interrupted run: fetch again

    def put(self, key: str, value: Any) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value), encoding="utf-8")
        tmp.replace(path)
