"""
Small shared helpers: hashing, canonical JSON, timestamps, and term
extraction. Nothing here knows what a corpus is.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

PROTOCOL = "networked-mplpb/0.1"

_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """a an and are as at be but by can do does for from has have how i in
    into is it its of on or should that the their them then there these this
    to was were what when where which who why will with you your about
    between must not only than too very""".split()
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def stamp(version: int = 1) -> str:
    """The `mplpb:updated` format: ISO 8601 with timezone, space, v<n>."""
    return f"{now_iso()} v{version}"


def parse_iso(text: str) -> datetime:
    text = text.split()[0].replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def canonical(obj) -> bytes:
    """Deterministic JSON bytes: the thing that gets hashed and signed."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def stem(word: str) -> str:
    """Deliberately crude: strip a plural or -ing. Enough to match
    'kilns'/'kiln' and 'firing'/'fir' consistently on both sides of a
    comparison, without pulling in a stemmer."""
    for suffix, keep in (("ies", "y"), ("ing", ""), ("es", ""), ("s", "")):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)] + keep
    return word


def terms(text: str) -> list[str]:
    return [
        stem(w)
        for w in _WORD.findall((text or "").lower())
        if w not in STOPWORDS and len(w) > 2
    ]


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:60] or "page"
