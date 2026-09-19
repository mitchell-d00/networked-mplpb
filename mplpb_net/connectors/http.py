from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import quote

from .base import Connector, Unavailable


class HttpConnector(Connector):
    """A node served over HTTP by `mplpb-net serve` or by any static web
    server pointed at the node directory. GET only; no API."""

    scheme = "http"

    def read(self, rel: str) -> bytes:
        url = self.endpoint.rstrip("/") + "/" + quote(self.clean(rel))
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise Unavailable(f"{url}: {exc}") from exc
