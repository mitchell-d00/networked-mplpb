"""
Page parsing and rendering -- the one place that knows what an MPLPB page
looks like.

Compatible with MPLPB-LOCAL-008 v4 §5: the same required `mplpb:*` meta
fields, the same `updated` format, the same `_log/superseded/` convention,
and the same `<!-- mplpb:entries -->` insertion marker used by the Smart Local
front end. A corpus built here is readable by that front end and vice versa.

Networked MPLPB adds optional fields and never makes a local field mean
something different:

    mplpb:origin         human | machine | ratified
    mplpb:origin-depth   derivational distance from a human or ratified source
    mplpb:derived-from   space-separated refs this page was derived from
    mplpb:ratified-by    who ratified a machine-derived page (required if ratified)
    mplpb:ratified-at    when
    mplpb:diverges-from  a qualified ref in another corpus this page departs from

A qualified ref is `<corpus-id>:<document-id>`. An unqualified ref is local.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

REQUIRED_META = (
    "mplpb:document-id",
    "mplpb:category",
    "mplpb:updated",
    "mplpb:scope",
    "mplpb:when-to-use",
    "mplpb:status",
)

VALID_STATUS = ("current", "retired")
VALID_ORIGIN = ("human", "machine", "ratified")

ROOT_PAGE = "index.html"
SUB_INDEX = "_index.html"
LOG_DIR = "_log"
SUPERSEDED_DIR = "superseded"
NET_DIR = "_net"
ENTRY_MARKER = "<!-- mplpb:entries -->"

UPDATED_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:?\d{2})\s+v(\d+)$"
)

_NON_LOCAL = ("http://", "https://", "mailto:", "#", "data:", "javascript:")


def is_internal(href: str) -> bool:
    return bool(href) and not href.lower().startswith(_NON_LOCAL)


def is_absolute(href: str) -> bool:
    return href.startswith("/") or href.lower().startswith("file:") or bool(
        re.match(r"^[a-zA-Z]:[\\/]", href)
    )


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class _Parser(HTMLParser):
    SKIP = {"script", "style", "head", "title", "nav"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []
        self.title = ""
        self.chunks: list[str] = []
        self._skip = 0
        self._in_title = False
        self._card = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self._card:
            if tag == "div":
                self._card += 1
        elif tag == "div" and "record" in (a.get("class") or "").split():
            self._card = 1
        name = (a.get("name") or "").strip()
        if tag == "meta" and name.startswith("mplpb:"):
            self.meta[name] = (a.get("content") or "").strip()
        if tag in ("link", "a") and a.get("href"):
            for r in (a.get("rel") or "").split() or [""]:
                self.links.append({"rel": r.lower(), "href": a["href"].strip()})
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP or (tag == "p" and "eyebrow" in (a.get("class") or "").split()):
            self._skip += 1
            if tag == "p":
                self._eyebrow = True

    def handle_endtag(self, tag):
        if self._card and tag == "div":
            self._card -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "p" and getattr(self, "_eyebrow", False) and self._skip:
            self._skip -= 1
            self._eyebrow = False

    def handle_data(self, data):
        if self._card:
            return
        if self._in_title:
            self.title += data.strip()
        elif not self._skip and data.strip():
            self.chunks.append(data.strip())


@dataclass
class Page:
    path: Path
    root: Path
    meta: dict = field(default_factory=dict)
    links: list = field(default_factory=list)
    title: str = ""
    text: str = ""

    @classmethod
    def load(cls, path: Path, root: Path) -> "Page":
        return cls.parse(Path(path).read_text(encoding="utf-8", errors="replace"), path, root)

    @classmethod
    def parse(cls, source: str, path: Path, root: Path) -> "Page":
        p = _Parser()
        p.feed(source)
        return cls(Path(path), Path(root), p.meta, p.links, p.title, " ".join(p.chunks))

    def get(self, key: str) -> str:
        return self.meta.get(f"mplpb:{key}", "")

    @property
    def rel(self) -> str:
        return self.path.resolve().relative_to(self.root.resolve()).as_posix()

    @property
    def document_id(self) -> str:
        return self.get("document-id")

    @property
    def status(self) -> str:
        return self.get("status")

    @property
    def updated(self) -> str:
        return self.get("updated")

    @property
    def version(self) -> int:
        m = UPDATED_RE.match(self.updated)
        return int(m.group(3)) if m else 0

    @property
    def scope(self) -> str:
        return self.get("scope")

    @property
    def supersedes(self) -> list[str]:
        return self.get("supersedes").split()

    @property
    def origin(self) -> str:
        return self.get("origin") or "human"

    @property
    def origin_depth(self) -> int:
        raw = self.get("origin-depth")
        try:
            return int(raw) if raw else (1 if self.origin == "machine" else 0)
        except ValueError:
            return -1

    @property
    def derived_from(self) -> list[str]:
        return self.get("derived-from").split()

    @property
    def is_root(self) -> bool:
        return self.rel == ROOT_PAGE

    @property
    def is_index(self) -> bool:
        return self.path.name in (ROOT_PAGE, SUB_INDEX)

    @property
    def in_superseded(self) -> bool:
        parts = Path(self.rel).parts
        return len(parts) >= 2 and parts[0] == LOG_DIR and parts[1] == SUPERSEDED_DIR

    @property
    def spoke(self) -> str:
        parts = Path(self.rel).parts
        return parts[0] if len(parts) > 1 else ""

    @property
    def rels(self) -> set:
        return {link["rel"] for link in self.links if link["rel"]}

    def internal_hrefs(self) -> list[str]:
        return [
            link["href"].split("#")[0]
            for link in self.links
            if is_internal(link["href"]) and link["href"].split("#")[0]
        ]

    def resolve(self, href: str) -> Path:
        return (self.path.parent / href.split("#")[0]).resolve()


def load_all(root: Path) -> dict[Path, Page]:
    root = Path(root).resolve()
    return {p.resolve(): Page.load(p, root) for p in sorted(root.rglob("*.html"))}


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def render_page(
    *,
    title: str,
    document_id: str,
    category: str,
    scope: str,
    when_to_use: str,
    body: str,
    rel_path: str,
    owner: str = "",
    status: str = "current",
    updated: str = "",
    supersedes: str = "",
    eyebrow: str = "",
    extra_meta: dict | None = None,
    related: list[tuple[str, str]] | None = None,
) -> str:
    """Render a complete page. `rel_path` is where the page will live,
    relative to the corpus root; it fixes the relative links upward."""
    from .util import stamp

    depth = len(Path(rel_path).parts) - 1
    up = "../" * depth
    is_root = rel_path == ROOT_PAGE
    meta = {
        "document-id": document_id,
        "category": category,
        "updated": updated or stamp(1),
        "scope": scope,
        "owner": owner,
        "when-to-use": when_to_use,
        "status": status,
        "supersedes": supersedes,
    }
    meta.update(extra_meta or {})
    meta_lines = "\n".join(
        f'<meta name="mplpb:{k}" content="{esc(str(v))}">' for k, v in meta.items()
    )
    head_links = f'<link rel="stylesheet" href="{up}style.css">'
    if not is_root:
        head_links += f'\n<link rel="index" href="{up}index.html">\n<link rel="up" href="./_index.html">'
        if Path(rel_path).name == SUB_INDEX:
            head_links = (
                f'<link rel="stylesheet" href="{up}style.css">\n'
                f'<link rel="index" href="{up}index.html">\n<link rel="up" href="{up}index.html">'
            )
    card_rows = "".join(
        f"  <dt>{label}</dt><dd>{esc(str(meta.get(key, '')))}</dd>\n"
        for label, key in (
            ("Document ID", "document-id"),
            ("Category", "category"),
            ("Updated", "updated"),
            ("Owner", "owner"),
            ("Scope", "scope"),
            ("Status", "status"),
        )
        if meta.get(key)
    )
    for key in ("origin", "origin-depth"):
        if key in meta:
            card_rows += f"  <dt>{key.replace('-', ' ').title()}</dt><dd>{esc(str(meta[key]))}</dd>\n"
    nav = related if related is not None else (
        [] if is_root else [("./_index.html", "Up to the Sub-Index"), (f"{up}index.html", "Back to the Main Index")]
    )
    nav_html = ""
    if nav:
        nav_html = '<nav class="related">\n' + "\n".join(
            f'  <a href="{esc(h)}">{esc(t)}</a>' for h, t in nav
        ) + "\n</nav>\n"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
{meta_lines}
{head_links}
</head>
<body>
<main>
<p class="eyebrow">{esc(eyebrow or 'MPLPB networked corpus')}</p>
<h1>{esc(title)}</h1>

<div class="record"><dl>
{card_rows}</dl></div>

{body}
{nav_html}</main>
</body>
</html>
"""


def insert_entry(path: Path, entry_html: str) -> None:
    """Append a list entry before the insertion marker. Append-only: the
    marker is the only place new lines go, so existing entries are never
    rewritten."""
    text = path.read_text(encoding="utf-8")
    if ENTRY_MARKER not in text:
        raise ValueError(f"{path} has no {ENTRY_MARKER} marker")
    text = text.replace(ENTRY_MARKER, entry_html.rstrip() + "\n" + ENTRY_MARKER, 1)
    path.write_text(text, encoding="utf-8")


def bump_updated(path: Path) -> None:
    """Increment the version token of an index/log page after appending."""
    from .util import now_iso

    text = path.read_text(encoding="utf-8")
    m = re.search(r'(<meta name="mplpb:updated" content=")([^"]*)(">)', text)
    if not m:
        return
    vm = UPDATED_RE.match(m.group(2))
    version = int(vm.group(3)) + 1 if vm else 1
    new = f"{now_iso()} v{version}"
    text = text[: m.start(2)] + new + text[m.end(2):]
    text = re.sub(r"(<dt>Updated</dt><dd>)[^<]*(</dd>)", rf"\g<1>{new}\g<2>", text, count=1)
    path.write_text(text, encoding="utf-8")
