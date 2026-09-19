"""
Connectors -- how bytes get from somewhere else to here.

A connector knows one thing: read the file at a relative path under an
endpoint. It does not know what a corpus, node, or hub is, and it never
interprets what it reads. That keeps transport replaceable (§12): the same
node served over HTTP, mounted from a USB stick, or packed in a ZIP archive
is the same node, verified the same way.

Endpoints are strings:

    file:///abs/path/to/node      a directory on a mounted filesystem
    zip:///abs/path/to/node.zip   an archive carried by hand
    http://host:port/             a node served by `mplpb-net serve`

Adding a transport means adding a class with `read()` and registering its
scheme below. Nothing else changes.
"""

from __future__ import annotations

from .base import Connector, Unavailable
from .filesystem import FileConnector
from .archive import ZipConnector
from .http import HttpConnector

SCHEMES = {"file": FileConnector, "zip": ZipConnector, "http": HttpConnector, "https": HttpConnector}
NETWORK_SCHEMES = {"http", "https"}


def scheme_of(endpoint: str) -> str:
    return endpoint.split(":", 1)[0].lower() if ":" in endpoint else "file"


def connect(endpoint: str, cfg: dict | None = None) -> Connector:
    cfg = cfg or {}
    scheme = scheme_of(endpoint)
    if scheme not in SCHEMES:
        raise Unavailable(f"no connector for scheme {scheme!r}")
    allowed = set(cfg.get("allow_connectors", SCHEMES))
    if scheme == "https":
        scheme_key = "http"
    else:
        scheme_key = scheme
    if scheme_key not in allowed:
        raise Unavailable(f"connector {scheme_key!r} disabled by allow_connectors")
    if cfg.get("offline") and scheme in NETWORK_SCHEMES:
        raise Unavailable("node is offline; network connectors refused")
    return SCHEMES[scheme](endpoint, timeout=float(cfg.get("timeout_seconds", 5.0)))


__all__ = ["Connector", "Unavailable", "connect", "scheme_of", "FileConnector", "ZipConnector", "HttpConnector"]
