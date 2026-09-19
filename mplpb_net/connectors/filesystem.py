from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from .base import Connector, Unavailable


class FileConnector(Connector):
    """A node directory on a filesystem this machine can see: a local disk,
    a mounted USB stick, a network share. No network protocol involved."""

    scheme = "file"

    def __init__(self, endpoint: str, timeout: float = 5.0):
        super().__init__(endpoint, timeout)
        path = unquote(urlparse(endpoint).path) if endpoint.startswith("file:") else endpoint
        self.base = Path(path)

    def read(self, rel: str) -> bytes:
        target = (self.base / self.clean(rel)).resolve()
        try:
            target.relative_to(self.base.resolve())
        except ValueError as exc:
            raise Unavailable(f"path escapes endpoint: {rel}") from exc
        if not self.base.exists():
            raise Unavailable(f"{self.base} is not present")
        try:
            return target.read_bytes()
        except OSError as exc:
            raise Unavailable(f"{self.endpoint} {rel}: {exc}") from exc
