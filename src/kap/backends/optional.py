from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

import httpx

from ..models.disclosure import Disclosure


class MkkProvider(Protocol):
    """Optional MKK-backed provider contract for identity and disclosure enrichment."""

    def resolve_member_oid(self, ticker_or_name: str) -> str | None:
        """Resolve a ticker or company name to an MKK member OID."""

    def fetch_disclosures(
        self,
        member_oid: str,
        *,
        from_index: int | None = None,
    ) -> Iterable[Disclosure]:
        """Yield disclosures after the supplied checkpoint."""


@dataclass(frozen=True)
class AttachmentDownloadResult:
    url: str
    path: Path
    size_bytes: int


class AttachmentDownloader(Protocol):
    """Optional attachment download contract."""

    def download(self, url: str, destination_dir: Path) -> AttachmentDownloadResult:
        """Download one attachment and return its local path and size."""


_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class HttpAttachmentDownloader:
    """Small opt-in HTTP attachment downloader with safe deterministic filenames."""

    def __init__(self, timeout_s: float = 30.0, client: httpx.Client | None = None) -> None:
        self.timeout_s = timeout_s
        self._client = client

    def download(self, url: str, destination_dir: Path) -> AttachmentDownloadResult:
        destination_dir.mkdir(parents=True, exist_ok=True)
        if self._client is not None:
            response = self._client.get(url)
        else:
            with httpx.Client(timeout=self.timeout_s) as client:
                response = client.get(url)
        response.raise_for_status()
        name = url.rstrip("/").rsplit("/", 1)[-1] or "attachment.bin"
        name = _FILENAME_RE.sub("_", name)[:180] or "attachment.bin"
        path = destination_dir / name
        path.write_bytes(response.content)
        return AttachmentDownloadResult(url=url, path=path, size_bytes=path.stat().st_size)


class CheckpointStore(Protocol):
    """Persistence contract for incremental polling cursors."""

    def load(self, stream_key: str) -> int | None:
        """Read the last processed disclosure index."""

    def save(self, stream_key: str, disclosure_index: int) -> None:
        """Persist the last processed disclosure index."""


class JsonCheckpointStore:
    """Atomic JSON checkpoint store with no database dependency."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def load(self, stream_key: str) -> int | None:
        value = self._read().get(stream_key)
        return int(value) if value is not None else None

    def save(self, stream_key: str, disclosure_index: int) -> None:
        values = self._read()
        values[stream_key] = int(disclosure_index)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f".{self.path.name}.tmp")
        temp_path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)


class IncrementalDisclosurePoller:
    """Filter a disclosure fetcher by checkpoint and advance it atomically."""

    def __init__(
        self,
        fetcher: Callable[[int | None], Iterable[Disclosure]],
        checkpoints: CheckpointStore,
    ) -> None:
        self.fetcher = fetcher
        self.checkpoints = checkpoints

    def poll(self, stream_key: str) -> list[Disclosure]:
        last_index = self.checkpoints.load(stream_key)
        rows = list(self.fetcher(last_index))
        new_rows = [row for row in rows if last_index is None or row.disclosure_index > last_index]
        new_rows.sort(key=lambda row: row.disclosure_index)
        if new_rows:
            self.checkpoints.save(stream_key, new_rows[-1].disclosure_index)
        return new_rows
