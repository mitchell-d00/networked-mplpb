from __future__ import annotations

import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from .base import Connector, Unavailable


class ZipConnector(Connector):
    """A node packed into a ZIP archive and carried by hand (sneakernet).
    The archive may hold the node at its top level or inside one folder."""

    scheme = "zip"

    def __init__(self, endpoint: str, timeout: float = 5.0):
        super().__init__(endpoint, timeout)
        self.path = Path(unquote(urlparse(endpoint).path))

    def _prefix(self, zf: zipfile.ZipFile) -> str:
        names = zf.namelist()
        if "node.json" in names:
            return ""
        for n in names:
            if n.endswith("/node.json") and n.count("/") == 1:
                return n[: -len("node.json")]
        return ""

    def read(self, rel: str) -> bytes:
        if not self.path.exists():
            raise Unavailable(f"{self.path} is not present")
        try:
            with zipfile.ZipFile(self.path) as zf:
                return zf.read(self._prefix(zf) + self.clean(rel))
        except (KeyError, zipfile.BadZipFile, OSError) as exc:
            raise Unavailable(f"{self.endpoint} {rel}: {exc}") from exc
