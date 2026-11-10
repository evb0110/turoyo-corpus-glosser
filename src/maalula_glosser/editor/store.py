"""Where editor sessions live on disk.

One JSON file per document under `data/editor_sessions/`, written atomically so
an interrupted save cannot truncate a session. This is the file the user
reopens; it is the whole editable state, nothing derived.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from maalula_glosser.editor import session as S
from maalula_glosser.io_utils import atomic_write_text, read_json
from maalula_glosser.state import writable
import json


class SessionStore:
    def __init__(self, root: Path | str = "."):
        self.root = Path(root)
        self.dir = writable(self.root, "data/editor_sessions")
        # (kind, path) -> ((inode, mtime_ns, size), value); see `_cached`
        self._cache: dict[tuple[str, Path], tuple[tuple[int, int, int], Any]] = {}
        self._cache_lock = threading.Lock()

    def path(self, document_id: str) -> Path:
        # document ids are stable_id output (edoc_<hex>), so they are safe file
        # names; guard anyway against a hand-edited id escaping the directory
        safe = "".join(c for c in document_id if c.isalnum() or c in "_-")
        if not safe:
            raise S.SessionError("empty document id")
        return self.dir / f"{safe}.json"

    def save(self, document: dict[str, Any]) -> Path:
        S.normalize_morphology(document)
        S.validate(document)
        document["updated"] = S.now()
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.path(document["document_id"])
        atomic_write_text(target, json.dumps(document, ensure_ascii=False, indent=1))
        return target

    def load(self, document_id: str) -> dict[str, Any]:
        data = read_json(self.path(document_id), None)
        if data is None:
            raise FileNotFoundError(document_id)
        S.normalize_morphology(data)
        return S.validate(data)

    def trash(self, document_id: str) -> Path:
        """Move a session out of the live list rather than deleting it: a
        stray click on the wrong row should be recoverable, and a folder is
        cheaper to reason about than an undo stack that outlives the process
        (`history.History` is in memory only, see its own docstring)."""
        source = self.path(document_id)
        if not source.exists():
            raise FileNotFoundError(document_id)
        trash_dir = self.dir / ".trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        target = trash_dir / source.name
        if target.exists():
            # already-trashed id (rare: only if trashed, restored by hand,
            # then trashed again) — keep both rather than overwrite one
            target = trash_dir / f"{source.stem}.{S.now().replace(':', '-')}{source.suffix}"
        source.rename(target)
        return target

    def exists(self, document_id: str) -> bool:
        """Whether the document is on the shelf, without parsing it: the lock
        routes ask this every few seconds per open tab, and a large FLEx
        session takes about a second to parse."""
        return self.path(document_id).is_file()

    def summary(self, document_id: str, kind: str,
                compute: Callable[[dict[str, Any]], Any]) -> Any:
        """`compute(self.load(document_id))`, remembered until the file
        changes. For the project-wide passes (review totals, statistics) that
        need a little from every document: re-parsing the whole shelf on every
        click took 15 s and most of the server's memory once the shelf grew to
        hundreds of megabytes. The result is shared between callers, so
        `compute` must return something they will not mutate."""
        path = self.path(document_id)
        return self._cached(path, kind, lambda: compute(self.load(document_id)))

    def _cached(self, path: Path, kind: str, compute: Callable[[], Any]) -> Any:
        # Every write goes through `atomic_write_text`, a rename onto the
        # path, so any change gives the file a new inode or mtime or size.
        # The stamp is taken before reading: a write that lands in between
        # leaves a stale stamp, which only costs one extra parse next time.
        st = path.stat()
        stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
        key = (kind, path)
        with self._cache_lock:
            hit = self._cache.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        value = compute()
        with self._cache_lock:
            self._cache[key] = (stamp, value)
        return value

    def _row(self, path: Path) -> dict[str, Any] | None:
        data = read_json(path, None)
        if not isinstance(data, dict):
            return None
        return {"document_id": data.get("document_id"),
                "title": data.get("title") or "(untitled)",
                "updated": data.get("updated"),
                "counts": S.counts(data)}

    def list(self) -> list[dict[str, Any]]:
        if not self.dir.exists():
            return []
        rows = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                row = self._cached(path, "row", lambda: self._row(path))
            except FileNotFoundError:
                continue  # trashed or renamed between glob and stat
            if row is None:
                continue
            # callers annotate their rows (e.g. `holder_name`), so hand out
            # copies and keep the cached row pristine
            rows.append({**row, "counts": dict(row["counts"])})
        rows.sort(key=lambda r: r.get("updated") or "", reverse=True)
        return rows
