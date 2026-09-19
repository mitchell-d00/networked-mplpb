"""
Validation -- the local eight checks of MPLPB-LOCAL-008 v4 §11, plus the
network checks N.1 to N.8 that make a corpus safe to copy and federate.

CHECKS is the single source for both the code below and the plain-language
page spec/validation.html that every seed carries. A test enforces that
every check implemented here is described there, so the prose rules and the
code cannot drift apart silently.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .page import (
    LOG_DIR,
    NET_DIR,
    REQUIRED_META,
    ROOT_PAGE,
    SUPERSEDED_DIR,
    UPDATED_RE,
    VALID_ORIGIN,
    VALID_STATUS,
    inside,
    is_absolute,
    load_all,
)
from .util import canonical, read_json, sha256_bytes, sha256_file

CHECKS = {
    "11.1": ("Link validity", "FM-L1",
             "Every link from one page of the corpus to another file of the corpus is relative "
             "and points at a file that exists."),
    "11.2": ("Root reachability", "FM-L2",
             "Every page that is not a retired page can be reached by following links from "
             "index.html."),
    "11.3": ("Required metadata", "FM-L3",
             "Every page declares document-id, category, updated, scope, when-to-use and status "
             "as mplpb meta tags; status is current or retired; every page except index.html "
             "has a rel=index link and a rel=up link."),
    "11.4": ("Unique identity", "",
             "No two current pages share a document ID."),
    "11.5": ("Supersession consistency", "FM-L6",
             "Retired pages live under _log/superseded/ and nowhere else; pages there are "
             "retired; every supersedes value names a retired page; no navigation index links "
             "a retired page."),
    "11.6": ("Boundary safety", "FM-L4",
             "No link resolves to a location outside the corpus directory."),
    "11.7": ("Index consistency", "",
             "Every current page is listed in its spoke's _index.html, or in index.html if it "
             "belongs to no spoke."),
    "11.8": ("Timestamp format", "FM-L9",
             "Every updated value is an ISO 8601 time with a timezone, a space, and a version "
             "token such as v3."),
    "N.1": ("Corpus identity", "FM-N14",
            "_net/corpus.json exists and declares protocol, corpus_id, title, kind, scope, "
            "scope_terms, relation and seeded_from; relation is origin, descendant, fork or "
            "partial; anything but origin names the corpus ID and fingerprint it was seeded "
            "from; _net/_index.html repeats the corpus ID and carries the SHA-256 of "
            "corpus.json so the human twin cannot silently disagree with the machine file."),
    "N.2": ("Manifest integrity", "FM-N12",
            "_net/manifest.json lists every file in the corpus except itself with its SHA-256; "
            "every hash matches; no file is unlisted; manifest_sha256 is the SHA-256 of the "
            "file list written as compact JSON with sorted keys."),
    "N.3": ("Lineage chain", "FM-N12",
            "_net/lineage.json is a list of events numbered from 0; each event's prev field is "
            "the SHA-256 of the previous event as compact sorted JSON (empty for the first); "
            "the last event names this corpus's ID."),
    "N.4": ("Declared scope", "FM-N1",
            "The corpus declares a non-empty scope sentence and at least one scope term, and "
            "every scope term appears in _net/vocabulary.json."),
    "N.5": ("No machine identity inside", "FM-N14",
            "The corpus contains no node description, key file, or configuration: those "
            "belong to the machine carrying it, so copying the corpus never copies a "
            "machine's identity."),
    "N.6": ("Scoped supersession", "FM-N6",
            "A supersedes value may only name a document in this corpus. A page that departs "
            "from another corpus's document says so with diverges-from."),
    "N.7": ("Origin depth", "FM-N7",
            "origin is human, machine or ratified; human and ratified pages have depth 0; "
            "machine pages have depth 1 or more and at least one greater than any local page "
            "they are derived from; a ratified page names who ratified it and when."),
    "N.8": ("Seed completeness", "FM-N10",
            "The corpus carries what a stranger needs: index.html with a boot block, BOOT.md, "
            "spec/seed.html, spec/validation.html, _log/revisions.html and every _net file, so "
            "a copy can instantiate another copy without asking anyone."),
}


@dataclass(frozen=True)
class Finding:
    check: str
    path: str
    message: str

    @property
    def failure_mode(self) -> str:
        return CHECKS.get(self.check, ("", "", ""))[1]

    def __str__(self) -> str:
        fm = f" [{self.failure_mode}]" if self.failure_mode else ""
        where = f"{self.path}: " if self.path else ""
        return f"{self.check}{fm}  {where}{self.message}"


@dataclass
class Report:
    root: Path
    findings: list
    pages: int = 0
    current: int = 0
    retired: int = 0

    @property
    def ok(self) -> bool:
        return not self.findings

    def failed(self) -> set:
        return {f.check for f in self.findings}

    def summary(self) -> str:
        head = (f"validated {self.pages} page(s) under {self.root} "
                f"({self.current} current, {self.retired} retired)")
        if self.ok:
            return head + f"\n  OK    {len(CHECKS)} checks clean (11.1-11.8, N.1-N.8)"
        lines = [head] + [f"  FAIL  {f}" for f in sorted(self.findings, key=str)]
        return "\n".join(lines + [f"\n{len(self.findings)} problem(s)"])


REQUIRED_FILES = (
    ROOT_PAGE, "BOOT.md", "spec/seed.html", "spec/validation.html",
    f"{LOG_DIR}/revisions.html", f"{NET_DIR}/corpus.json", f"{NET_DIR}/vocabulary.json",
    f"{NET_DIR}/lineage.json", f"{NET_DIR}/catalog.json", f"{NET_DIR}/manifest.json",
    f"{NET_DIR}/_index.html",
)
FORBIDDEN_NAMES = {"node.json", "node.html", "config.json", "node.key"}


def validate(root: Path, *, only: set | None = None) -> Report:
    root = Path(root).resolve()
    findings: list[Finding] = []

    def fail(check, path, message):
        if only is None or check in only:
            findings.append(Finding(check, path, message))

    if not (root / ROOT_PAGE).exists():
        return Report(root, [Finding("11.2", "", f"no {ROOT_PAGE} at {root}")])
    pages = load_all(root)
    entry = (root / ROOT_PAGE).resolve()

    # -- local checks ----------------------------------------------------------
    for page in pages.values():
        for href in page.internal_hrefs():
            if is_absolute(href):
                fail("11.1", page.rel, f"non-relative link -> {href}")
                continue
            target = page.resolve(href)
            if not inside(target, root):
                fail("11.6", page.rel, f"link escapes root -> {href}")
            elif not target.exists():
                fail("11.1", page.rel, f"broken link -> {href}")
        for key in REQUIRED_META:
            if not page.meta.get(key):
                fail("11.3", page.rel, f"missing {key}")
        if page.status and page.status not in VALID_STATUS:
            fail("11.3", page.rel, f"status must be current|retired, got '{page.status}'")
        if not page.is_root:
            for need in ("index", "up"):
                if need not in page.rels:
                    fail("11.3", page.rel, f'missing rel="{need}"')
        if page.updated and not UPDATED_RE.match(page.updated):
            fail("11.8", page.rel, f"updated '{page.updated}' is not '<ISO8601+tz> v<n>'")

    holders: dict = {}
    for page in pages.values():
        if page.status == "current" and page.document_id:
            holders.setdefault(page.document_id, []).append(page.rel)
    for did, rels in holders.items():
        if len(rels) > 1:
            fail("11.4", "", f"duplicate current document ID {did}: {', '.join(sorted(rels))}")

    seen, queue = {entry}, deque([entry])
    while queue:
        page = pages[queue.popleft()]
        for href in page.internal_hrefs():
            target = page.resolve(href)
            if target in pages and target not in seen:
                seen.add(target)
                queue.append(target)
    for resolved, page in pages.items():
        if not page.in_superseded and resolved not in seen:
            fail("11.2", page.rel, "orphan, unreachable from index.html")

    retired_ids = {p.document_id for p in pages.values() if p.status == "retired"}
    for page in pages.values():
        if page.status == "retired" and not page.in_superseded:
            fail("11.5", page.rel, f"retired but not under {LOG_DIR}/{SUPERSEDED_DIR}/")
        if page.in_superseded and page.status != "retired":
            fail("11.5", page.rel, "under the superseded directory but not retired")
        for ref in page.supersedes:
            local = ref.split(":", 1)[1] if ref.startswith("C-") and ":" in ref else ref
            if local not in retired_ids:
                fail("11.5", page.rel, f"supersedes {ref}, which is not a retired page here")
        if page.is_index:
            for href in page.internal_hrefs():
                target = pages.get(page.resolve(href))
                if target is not None and target.status == "retired":
                    fail("11.5", page.rel, f"navigation index links retired page {href}")

    for resolved, page in pages.items():
        if page.is_index or page.in_superseded or page.status == "retired":
            continue
        holder = pages.get((page.path.parent / "_index.html").resolve()) or pages[entry]
        if not any(holder.resolve(h) == resolved for h in holder.internal_hrefs()):
            fail("11.7", page.rel, f"not listed in {holder.rel}")

    # -- network checks --------------------------------------------------------
    for rel in REQUIRED_FILES:
        if not (root / rel).exists():
            fail("N.8", rel, "missing; a copy could not instantiate another copy")
    root_page = pages.get(entry)
    if root_page is not None and "Boot block" not in (root / ROOT_PAGE).read_text(encoding="utf-8"):
        fail("N.8", ROOT_PAGE, "no boot block")

    ident = None
    try:
        ident = read_json(root / f"{NET_DIR}/corpus.json")
    except (FileNotFoundError, ValueError) as exc:
        fail("N.1", f"{NET_DIR}/corpus.json", f"unreadable: {exc}")
    if ident is not None:
        for key in ("protocol", "corpus_id", "title", "kind", "scope", "scope_terms", "relation"):
            if key not in ident or ident[key] in (None, ""):
                fail("N.1", f"{NET_DIR}/corpus.json", f"missing {key}")
        if ident.get("relation") not in ("origin", "descendant", "fork", "partial"):
            fail("N.1", f"{NET_DIR}/corpus.json", f"invalid relation {ident.get('relation')!r}")
        seeded = ident.get("seeded_from")
        if ident.get("relation") != "origin" and not (
            seeded and seeded.get("corpus_id") and seeded.get("manifest_sha256")
        ):
            fail("N.1", f"{NET_DIR}/corpus.json", "non-origin corpus without seeded_from")
        twin = pages.get((root / f"{NET_DIR}/_index.html").resolve())
        if twin is not None:
            if twin.get("corpus-id") != ident.get("corpus_id"):
                fail("N.1", twin.rel, "twin corpus-id disagrees with corpus.json")
            if twin.get("corpus-sha256") != sha256_file(root / f"{NET_DIR}/corpus.json"):
                fail("N.1", twin.rel, "twin is stale: corpus.json changed since it was built")

        if not str(ident.get("scope", "")).strip():
            fail("N.4", f"{NET_DIR}/corpus.json", "empty scope")
        terms_ = ident.get("scope_terms") or []
        if not terms_:
            fail("N.4", f"{NET_DIR}/corpus.json", "no scope terms")
        try:
            vocab = read_json(root / f"{NET_DIR}/vocabulary.json")
            for t in terms_:
                if t not in vocab:
                    fail("N.4", f"{NET_DIR}/vocabulary.json", f"scope term '{t}' not in vocabulary")
        except (FileNotFoundError, ValueError):
            pass

    try:
        manifest = read_json(root / f"{NET_DIR}/manifest.json")
        listed = manifest.get("files", {})
        if sha256_bytes(canonical(listed)) != manifest.get("manifest_sha256"):
            fail("N.2", f"{NET_DIR}/manifest.json", "manifest_sha256 does not match the file list")
        if ident and manifest.get("corpus_id") != ident.get("corpus_id"):
            fail("N.2", f"{NET_DIR}/manifest.json", "manifest names a different corpus")
        actual = {
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and p.relative_to(root).as_posix() != f"{NET_DIR}/manifest.json"
        }
        for rel in sorted(actual - set(listed)):
            fail("N.2", rel, "file not in manifest")
        for rel, digest in sorted(listed.items()):
            if rel not in actual:
                fail("N.2", rel, "listed in manifest but missing")
            elif sha256_file(root / rel) != digest:
                fail("N.2", rel, "content does not match manifest hash")
    except (FileNotFoundError, ValueError) as exc:
        fail("N.2", f"{NET_DIR}/manifest.json", f"unreadable: {exc}")

    try:
        events = read_json(root / f"{NET_DIR}/lineage.json")["events"]
        prev = ""
        for i, ev in enumerate(events):
            if ev.get("seq") != i:
                fail("N.3", f"{NET_DIR}/lineage.json", f"event {i} has seq {ev.get('seq')}")
            if ev.get("prev", "") != prev:
                fail("N.3", f"{NET_DIR}/lineage.json", f"event {i} breaks the hash chain")
            prev = sha256_bytes(canonical(ev))
        if not events:
            fail("N.3", f"{NET_DIR}/lineage.json", "no events")
        elif ident and events[-1].get("corpus_id") != ident.get("corpus_id"):
            fail("N.3", f"{NET_DIR}/lineage.json", "last event does not name this corpus")
    except (FileNotFoundError, ValueError, KeyError) as exc:
        fail("N.3", f"{NET_DIR}/lineage.json", f"unreadable: {exc}")

    for p in root.rglob("*"):
        if p.is_file() and (p.name in FORBIDDEN_NAMES or p.suffix == ".key"):
            fail("N.5", p.relative_to(root).as_posix(), "machine identity or configuration inside a corpus")

    cid = (ident or {}).get("corpus_id", "")
    current = {p.document_id: p for p in pages.values() if p.status == "current"}
    for page in pages.values():
        for ref in page.supersedes:
            if ref.startswith("C-") and ":" in ref and ref.split(":", 1)[0] != cid:
                fail("N.6", page.rel, f"supersedes {ref} in another corpus; use diverges-from")
        origin = page.origin
        depth = page.origin_depth
        if origin not in VALID_ORIGIN:
            fail("N.7", page.rel, f"origin must be one of {VALID_ORIGIN}")
            continue
        if origin in ("human", "ratified") and depth != 0:
            fail("N.7", page.rel, f"{origin} page must have depth 0, has {depth}")
        if origin == "machine" and depth < 1:
            fail("N.7", page.rel, "machine page must have depth >= 1")
        if origin == "ratified" and not (page.get("ratified-by") and page.get("ratified-at")):
            fail("N.7", page.rel, "ratified page must record ratified-by and ratified-at")
        if origin == "machine":
            for ref in page.derived_from:
                rcid, rdid = (ref.split(":", 1) if ref.startswith("C-") and ":" in ref else ("", ref))
                if (not rcid or rcid == cid) and rdid in current:
                    if depth < current[rdid].origin_depth + 1:
                        fail("N.7", page.rel,
                             f"depth {depth} but derived from {rdid} at depth {current[rdid].origin_depth}")

    n_current = sum(1 for p in pages.values() if p.status == "current")
    n_retired = sum(1 for p in pages.values() if p.status == "retired")
    return Report(root, findings, len(pages), n_current, n_retired)
