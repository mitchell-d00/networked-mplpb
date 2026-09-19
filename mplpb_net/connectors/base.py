from __future__ import annotations

import json
import posixpath


class Unavailable(Exception):
    """The endpoint could not be read. Failure to retrieve is information:
    callers report it rather than substituting something else."""


class Connector:
    scheme = ""

    def __init__(self, endpoint: str, timeout: float = 5.0):
        self.endpoint = endpoint
        self.timeout = timeout

    @staticmethod
    def clean(rel: str) -> str:
        rel = posixpath.normpath(rel.lstrip("/"))
        if rel.startswith("..") or rel.startswith("/"):
            raise Unavailable(f"refusing path outside endpoint: {rel}")
        return rel

    def read(self, rel: str) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError

    def read_json(self, rel: str):
        try:
            return json.loads(self.read(rel).decode("utf-8"))
        except ValueError as exc:
            raise Unavailable(f"{self.endpoint} {rel}: not JSON ({exc})") from exc

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.endpoint!r})"
