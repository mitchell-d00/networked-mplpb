"""
The corpus -- S = (A, I, R, P, V, B) on disk.

    A  artifacts       the HTML pages
    I  identifiers     document IDs, plus the corpus ID in _net/corpus.json
    R  relationships   relative links, supersession, lineage
    P  provenance      owner, origin, origin-depth, lineage, revision log
    V  validation      spec/validation.html (prose) + validate.py (code)
    B  boot            index.html boot block and BOOT.md

Everything the network needs to know about a corpus lives inside the corpus,
under `_net/`, as plain JSON with an HTML twin a browser can read:

    _net/corpus.json      identity, declared scope, relation, seeded-from
    _net/vocabulary.json  scope terms and their synonyms (the shared taxonomy)
    _net/lineage.json     append-only, hash-chained replication history
    _net/catalog.json     derived per-document records, for static retrieval
    _net/manifest.json    sha256 of every file; the corpus fingerprint
    _net/_index.html      the human-readable twin of the above

What does *not* live inside a corpus: node identity, keys, endpoints, or
peers. Those belong to the machine carrying the corpus, so copying a corpus
can never copy an identity (FM-N14).
"""

from __future__ import annotations

import re
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import page as pg
from .page import (
    ENTRY_MARKER,
    LOG_DIR,
    NET_DIR,
    ROOT_PAGE,
    SUB_INDEX,
    SUPERSEDED_DIR,
    Page,
    bump_updated,
    esc,
    insert_entry,
    load_all,
    render_page,
)
from .util import (
    PROTOCOL,
    canonical,
    now_iso,
    read_json,
    sha256_bytes,
    sha256_file,
    slugify,
    stamp,
    terms,
    write_json,
)

DATA = Path(__file__).resolve().parent / "data"

RELATIONS = ("origin", "descendant", "fork", "partial")
KINDS = ("knowledge", "hub")

CORPUS_JSON = f"{NET_DIR}/corpus.json"
VOCAB_JSON = f"{NET_DIR}/vocabulary.json"
LINEAGE_JSON = f"{NET_DIR}/lineage.json"
CATALOG_JSON = f"{NET_DIR}/catalog.json"
MANIFEST_JSON = f"{NET_DIR}/manifest.json"
TWIN = f"{NET_DIR}/_index.html"

#: Never listed in the manifest: the manifest cannot contain its own hash.
MANIFEST_EXCLUDE = {MANIFEST_JSON}


def new_corpus_id() -> str:
    return "C-" + secrets.token_hex(6).upper()


def qualify(corpus_id: str, document_id: str) -> str:
    return f"{corpus_id}:{document_id}"


def split_ref(ref: str) -> tuple[str, str]:
    """'C-ABC:DOC-1' -> ('C-ABC', 'DOC-1'); 'DOC-1' -> ('', 'DOC-1')."""
    if ":" in ref and ref.split(":", 1)[0].startswith("C-"):
        cid, did = ref.split(":", 1)
        return cid, did
    return "", ref


@dataclass
class Corpus:
    root: Path

    def __post_init__(self):
        self.root = Path(self.root).resolve()

    # -- identity -----------------------------------------------------------
    @property
    def identity(self) -> dict:
        return read_json(self.root / CORPUS_JSON)

    @property
    def corpus_id(self) -> str:
        return self.identity["corpus_id"]

    @property
    def vocabulary(self) -> dict:
        path = self.root / VOCAB_JSON
        return read_json(path) if path.exists() else {}

    @property
    def lineage(self) -> list:
        path = self.root / LINEAGE_JSON
        return read_json(path)["events"] if path.exists() else []

    @property
    def manifest(self) -> dict:
        return read_json(self.root / MANIFEST_JSON)

    @property
    def manifest_sha256(self) -> str:
        return self.manifest["manifest_sha256"]

    def exists(self) -> bool:
        return (self.root / CORPUS_JSON).exists()

    # -- lineage -------------------------------------------------------------
    def append_lineage(self, event: str, **detail) -> None:
        path = self.root / LINEAGE_JSON
        doc = read_json(path) if path.exists() else {"events": []}
        events = doc["events"]
        prev = sha256_bytes(canonical(events[-1])) if events else ""
        events.append(
            {
                "seq": len(events),
                "event": event,
                "corpus_id": detail.pop("corpus_id", None) or read_json(self.root / CORPUS_JSON)["corpus_id"],
                "at": now_iso(),
                "detail": detail,
                "prev": prev,
            }
        )
        write_json(path, doc)

    # -- derived files ---------------------------------------------------------
    def pages(self) -> dict:
        return load_all(self.root)

    def build_catalog(self) -> dict:
        records = []
        for page in sorted(self.pages().values(), key=lambda p: p.rel):
            records.append(
                {
                    "document_id": page.document_id,
                    "path": page.rel,
                    "title": page.title,
                    "category": page.get("category"),
                    "scope": page.scope,
                    "when_to_use": page.get("when-to-use"),
                    "status": page.status or "current",
                    "updated": page.updated,
                    "version": page.version,
                    "supersedes": page.supersedes,
                    "origin": page.origin,
                    "origin_depth": page.origin_depth,
                    "derived_from": page.derived_from,
                    "ratified_by": page.get("ratified-by"),
                    "is_index": page.is_index,
                    "sha256": sha256_file(page.path),
                    "text": page.text[:4000],
                }
            )
        catalog = {"protocol": PROTOCOL, "corpus_id": self.corpus_id, "documents": records}
        write_json(self.root / CATALOG_JSON, catalog)
        return catalog

    def build_twin(self) -> None:
        ident = self.identity
        ident_sha = sha256_file(self.root / CORPUS_JSON)
        seeded = ident.get("seeded_from") or {}
        lineage_rows = "".join(
            f"  <li><code>{esc(e['at'])}</code> {esc(e['event'])} "
            f"<code>{esc(e['corpus_id'])}</code> {esc(_detail(e['detail']))}</li>\n"
            for e in self.lineage
        )
        vocab_rows = "".join(
            f"  <li><strong>{esc(t)}</strong>"
            + (f" — also: {esc(', '.join(syn))}" if syn else "")
            + "</li>\n"
            for t, syn in sorted(self.vocabulary.items())
        )
        body = f"""<p>This page is the human-readable twin of the machine descriptors in
this directory. It is regenerated from them on every build; if the two
disagree, validation fails (check N.1).</p>

<h2>Identity</h2>
<ul class="map">
  <li>Corpus ID: <code>{esc(ident['corpus_id'])}</code></li>
  <li>Kind: {esc(ident.get('kind', 'knowledge'))}</li>
  <li>Relation: {esc(ident['relation'])}</li>
  <li>Seeded from: {esc(seeded.get('corpus_id', '—'))} {('at manifest <code>' + esc(seeded.get('manifest_sha256', '')[:16]) + '…</code>') if seeded else ''}</li>
  <li>Declared scope: {esc(ident['scope'])}</li>
  <li>Scope terms: {esc(', '.join(ident['scope_terms']))}</li>
</ul>
<p>A descendant or fork records where it was seeded from. That is lineage,
not endorsement: the source corpus has not reviewed anything written here
since.</p>

<h2>Vocabulary</h2>
<ul class="map">
{vocab_rows}</ul>

<h2>Lineage</h2>
<ul class="map">
{lineage_rows}</ul>

<h2>Machine files</h2>
<ul class="map">
  <li><a href="./corpus.json">corpus.json</a> — identity and scope</li>
  <li><a href="./vocabulary.json">vocabulary.json</a> — scope terms and synonyms</li>
  <li><a href="./lineage.json">lineage.json</a> — hash-chained replication history</li>
  <li><a href="./catalog.json">catalog.json</a> — derived document records</li>
  <li><a href="./manifest.json">manifest.json</a> — sha256 of every file</li>
</ul>
"""
        html_text = render_page(
            title="Corpus Identity",
            document_id="NET-CORPUS-000",
            category="Navigator / Network",
            scope="Corpus identity, declared scope, vocabulary, and lineage for the network",
            when_to_use="Identifying this corpus; checking where it was seeded from; routing decisions",
            body=body,
            rel_path=TWIN,
            owner=ident.get("owner", ""),
            updated=f"{now_iso()} v{max(1, len(self.lineage))}",
            eyebrow="MPLPB networked corpus · identity",
            extra_meta={
                "corpus-id": ident["corpus_id"],
                "corpus-sha256": ident_sha,
            },
        )
        (self.root / TWIN).write_text(html_text, encoding="utf-8")

    def compute_manifest(self) -> dict:
        files = {}
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                rel = path.relative_to(self.root).as_posix()
                if rel not in MANIFEST_EXCLUDE:
                    files[rel] = sha256_file(path)
        return {"corpus_id": self.corpus_id, "files": files, "manifest_sha256": sha256_bytes(canonical(files))}

    def build_manifest(self) -> dict:
        manifest = self.compute_manifest()
        write_json(self.root / MANIFEST_JSON, manifest)
        return manifest

    def build(self) -> dict:
        """Regenerate every derived file. The order matters: the manifest
        hashes the others, so it is always written last."""
        self.build_catalog()
        self.build_twin()
        return self.build_manifest()

    # -- lookup ------------------------------------------------------------------
    def find_current(self, document_id: str) -> Page | None:
        for p in self.pages().values():
            if p.document_id == document_id and p.status == "current":
                return p
        return None

    def log(self, entry: str) -> None:
        path = self.root / LOG_DIR / "revisions.html"
        insert_entry(path, f"  <li><code>{now_iso()[:10]}</code> {entry}</li>")
        bump_updated(path)


def _detail(detail: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in sorted(detail.items()) if v not in (None, "", []))


# ==========================================================================
# Seed creation
# ==========================================================================

def create_seed(
    root: Path,
    *,
    title: str,
    scope: str,
    scope_terms: list[str],
    owner: str = "",
    description: str = "",
    vocabulary: dict | None = None,
    kind: str = "knowledge",
    corpus_id: str | None = None,
) -> Corpus:
    """Write a seed that validates before it contains any domain content."""
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"{root} exists and is not empty")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    root.mkdir(parents=True, exist_ok=True)
    corpus = Corpus(root)
    cid = corpus_id or new_corpus_id()

    vocab = {t.lower(): [] for t in scope_terms}
    for term, syns in (vocabulary or {}).items():
        vocab.setdefault(term.lower(), [])
        vocab[term.lower()] = sorted(set(vocab[term.lower()]) | {s.lower() for s in syns})

    write_json(
        root / CORPUS_JSON,
        {
            "protocol": PROTOCOL,
            "corpus_id": cid,
            "title": title,
            "kind": kind,
            "scope": scope,
            "scope_terms": [t.lower() for t in scope_terms],
            "owner": owner,
            "relation": "origin",
            "seeded_from": None,
            "created": now_iso(),
        },
    )
    write_json(root / VOCAB_JSON, vocab)
    corpus.append_lineage("seeded", corpus_id=cid, title=title)
    shutil.copy(DATA / "style.css", root / "style.css")

    description = description or f"{title}. {scope}."
    _write_root(root, title, scope, owner, description, kind)
    _write_boot_md(root, title, description)
    _write_spec(root, owner)
    _write_log(root, owner)
    (root / LOG_DIR / SUPERSEDED_DIR).mkdir(parents=True, exist_ok=True)
    (root / LOG_DIR / SUPERSEDED_DIR / "README.txt").write_text(
        "Retired pages live here. They are deliberately unlinked from the\n"
        "navigation and are kept so that history can be reconstructed.\n",
        encoding="utf-8",
    )
    if kind == "hub":
        add_spoke(
            root,
            "nodes",
            title="Known Nodes",
            scope="Signed discovery descriptions of other nodes and hubs; where to look, never what is true",
            when_to_use="Finding which node carries a corpus whose declared scope owns a query",
            build=False,
        )
    corpus.log(f"NET-MAIN-000 seed created ({esc(cid)})")
    corpus.build()
    return corpus


def _write_root(root: Path, title: str, scope: str, owner: str, description: str, kind: str) -> None:
    body = f"""<h2>Boot block</h2>
<div class="boot">
<p><strong>What this corpus is.</strong> {esc(description)}</p>

<p><strong>Authoritative root.</strong> This file. Every internal link is
relative to it. The crawl boundary is this directory; a link resolving outside
it must be rejected.</p>

<p><strong>Identity.</strong> This corpus is identified by the corpus ID in
<a href="_net/_index.html">_net/</a>, not by where it is stored or which
machine serves it. Copying it does not copy any machine's identity.</p>

<p><strong>Retrieval rule.</strong> Answer corpus-dependent questions from
retrieved pages. Prefer <code>status: current</code> pages reachable from this
index. Cite a page by corpus ID, document ID, version, and status.</p>

<p><strong>Routing.</strong> A router decides where an answer should come from;
it does not write the answer. If a question belongs to another corpus, say
which. If several corpora plausibly own it, report the ambiguity. If the owner
is known but unreachable, say so; never impersonate it.</p>

<p><strong>Provenance.</strong> Anything retrieved from another corpus keeps
that corpus's identity. Transport is not authorship. Discovery is not
authority. Caching is not authorship.</p>

<p><strong>Change.</strong> Pages are superseded, never silently overwritten.
Retired versions live in <code>_log/superseded/</code>. A corpus may only
supersede its own documents.</p>

<p><strong>How to make another working copy.</strong> See
<a href="spec/seed.html">spec/seed.html</a>. The rules this corpus must
satisfy are written out in plain language in
<a href="spec/validation.html">spec/validation.html</a>, so they can be
re-implemented without the software that wrote them.</p>
</div>

<h2>Category map</h2>
<ul class="map">
  <li><a href="spec/_index.html">Specification &amp; Network Rules</a>
    <span class="scope">scope: how this corpus is built, copied, validated, routed, and cited</span></li>
  <li><a href="_net/_index.html">Corpus Identity</a>
    <span class="scope">scope: corpus ID, declared scope, vocabulary, lineage, manifest</span></li>
  <li><a href="_log/revisions.html">Revision log</a>
    <span class="scope">scope: append-only record of changes and supersessions</span></li>
{ENTRY_MARKER}
</ul>

<nav class="related">
  <a href="BOOT.md">BOOT.md — plain-text twin of this boot block</a>
</nav>
"""
    text = render_page(
        title=f"Main Index — {title}",
        document_id="NET-MAIN-000",
        category="Navigator / Main Index",
        scope=f"Entry point, crawl root, and routing map. Corpus scope: {scope}",
        when_to_use="First page read in any session; crawl entry point; uncertain which spoke owns a query",
        body=body,
        rel_path=ROOT_PAGE,
        owner=owner,
        eyebrow=f"MPLPB networked corpus · crawl root · {kind}",
        related=[],
    )
    (root / ROOT_PAGE).write_text(text, encoding="utf-8")


def _write_boot_md(root: Path, title: str, description: str) -> None:
    (root / "BOOT.md").write_text(
        f"""# BOOT — {title}

**Authoritative copy is `index.html`.** This twin exists for tools that read
markdown more readily than HTML. If the two disagree, `index.html` wins.

**What this corpus is.** {description}

**Identity.** `_net/corpus.json` (twin: `_net/_index.html`). The corpus ID
names the corpus, not the machine holding it.

**Retrieval rule.** Answer from retrieved pages. Prefer `status: current`.
Cite corpus ID, document ID, version, status.

**Routing.** Decide where, not what. Ambiguous ownership is reported, not
merged. A known-but-unreachable owner is reported, not impersonated.

**Provenance.** Transport is not authorship. Discovery is not authority.

**Change.** Supersede; never overwrite. Only supersede your own documents.

**Copy.** `spec/seed.html`. **Rules.** `spec/validation.html`.
""",
        encoding="utf-8",
    )


SPEC_PAGES = [
    (
        "seed.html",
        "NET-SPEC-001",
        "Instantiating a Copy",
        "How to turn this directory into another working corpus or node without the original author",
        "Copying this corpus; starting a new node; checking a copy is intact; seeding a descendant",
        """<p>This page is written for a reader who has a copy of this directory and
nothing else: no author, no original machine, possibly no software from the
project at all.</p>

<h2>1. Open it</h2>
<p>Open <code>index.html</code> in any browser. Every link is relative, so the
directory can live anywhere.</p>

<h2>2. Check it is intact</h2>
<p><code>_net/manifest.json</code> lists every file with its SHA-256 hash.
Compute the SHA-256 of each listed file with any tool you have
(<code>sha256sum</code>, <code>shasum -a 256</code>, <code>certutil</code>) and
compare. The corpus fingerprint is the SHA-256 of the file list written as
compact JSON with sorted keys. A file that is present but not listed, or
listed but different, means the copy is not the corpus it claims to be.</p>

<h2>3. Decide what the copy is</h2>
<p>A byte-identical copy is a <strong>mirror</strong>: same corpus ID, same
fingerprint, nothing to change. If you intend to add or change anything, the
copy becomes a new corpus and must say so:</p>
<ul>
<li><strong>descendant</strong> — a new corpus seeded from this one, owning a
new domain;</li>
<li><strong>fork</strong> — a new corpus that continues this one's domain under
separate governance;</li>
<li><strong>partial</strong> — a new corpus carrying only some spokes.</li>
</ul>
<p>In all three cases: give it a new corpus ID in
<code>_net/corpus.json</code>, set <code>relation</code>, record
<code>seeded_from</code> (the old corpus ID and fingerprint), and append an
event to <code>_net/lineage.json</code> whose <code>prev</code> field is the
SHA-256 of the previous event. Seeded-from is lineage, not endorsement.</p>

<h2>4. Make it a node</h2>
<p>A node is a machine that carries one or more corpora and publishes a small
signed description of them. The description lives outside every corpus, so a
copied corpus never carries a machine's identity. See
<a href="./network.html">Network Rules</a>.</p>

<h2>5. Validate</h2>
<p>The rules are in <a href="./validation.html">Validation Rules</a>. The
reference tool is <code>python3 -m mplpb_net validate &lt;dir&gt;</code>, but
nothing in the rules depends on it.</p>
""",
    ),
    (
        "network.html",
        "NET-SPEC-002",
        "Network Rules",
        "Routing by declared scope, provenance envelopes, origin depth, supersession across corpora",
        "Routing a query to another corpus; citing a remote page; deciding whether to serve machine-derived material",
        """<h2>Routing</h2>
<p>Each corpus declares a scope and a list of scope terms drawn from its
vocabulary. A router scores known corpora by how many query terms (and their
declared synonyms) appear in each scope. One clear leader owns the query.
Several close leaders are reported as <em>ambiguous</em>, with their lineage,
and are never merged. No match is reported as <em>not found in known
network</em>. A known owner that cannot be reached is reported as
<em>unavailable</em>; the router does not substitute another corpus's answer.
A byte-identical mirror of the same corpus ID may serve in its place, and the
citation still names both the corpus and the machine that served it.</p>

<h2>Provenance envelope</h2>
<p>Every retrieved page travels with: corpus ID, document ID, version, status,
origin, origin depth, content hash, the corpus fingerprint, the serving node,
and the route it took. The content hash must appear in the corpus manifest;
the fingerprint must appear in the serving node's signed description. A relay
or cache may add an attestation that it relayed the page. It may not change
who wrote it.</p>

<h2>Origin depth</h2>
<p>A human-authored page has depth 0. An unratified machine-produced page has
depth 1 or more. A page derived from others has depth one greater than the
deepest of them. Copying machine text verbatim does not reset depth; only a
recorded ratification (<code>ratified-by</code>, <code>ratified-at</code>)
does, and the ratification travels with the page. Depth is not truth. It is
derivational distance. Each node chooses its own maximum depth to serve.</p>

<h2>Supersession across corpora</h2>
<p>A corpus may supersede only its own documents. A descendant that disagrees
with its source records <code>diverges-from</code>, not
<code>supersedes</code>. The source's page stays the source's page.</p>
""",
    ),
]


def _write_spec(root: Path, owner: str) -> None:
    spec = root / "spec"
    spec.mkdir(parents=True, exist_ok=True)
    rows = ""
    for fname, did, title, scope, when, body in SPEC_PAGES:
        (spec / fname).write_text(
            render_page(
                title=title, document_id=did, category="Specification / Network",
                scope=scope, when_to_use=when, body=body, rel_path=f"spec/{fname}",
                owner=owner, eyebrow="MPLPB networked corpus · spec",
            ),
            encoding="utf-8",
        )
        rows += f'  <li><a href="./{fname}">{esc(title)}</a>\n    <span class="scope">scope: {esc(scope)}</span></li>\n'
    (spec / "validation.html").write_text(_validation_page(owner), encoding="utf-8")
    rows += ('  <li><a href="./validation.html">Validation Rules</a>\n'
             '    <span class="scope">scope: every structural check, in plain language</span></li>\n')
    index_body = f"""<p><strong>Scope.</strong> The rules this corpus is built from and the rules
it follows on a network. It does not own the content of any other spoke.</p>

<h2>Pages</h2>
<ul class="map">
{rows}{ENTRY_MARKER}
</ul>
"""
    (spec / SUB_INDEX).write_text(
        render_page(
            title="Specification & Network Rules", document_id="NET-SPEC-INDEX",
            category="Navigator / Sub-Index",
            scope="How this corpus is built, copied, validated, routed, and cited",
            when_to_use="Broad questions about the corpus format or network behaviour",
            body=index_body, rel_path=f"spec/{SUB_INDEX}", owner=owner,
            eyebrow="MPLPB networked corpus · sub-index",
            related=[("../index.html", "Back to the Main Index")],
        ),
        encoding="utf-8",
    )


def _validation_page(owner: str) -> str:
    from .validate import CHECKS

    rows = "".join(
        f"<h2>{esc(cid)} — {esc(title)}</h2>\n<p>{esc(text)}"
        + (f" <em>Failure mode: {esc(fm)}.</em>" if fm else "")
        + "</p>\n"
        for cid, (title, fm, text) in CHECKS.items()
    )
    body = f"""<p>These are the structural rules a copy of this corpus must satisfy. They are
written so that someone could re-implement them in any language, decades from
now, without the program that first enforced them. Passing them means the
corpus is well-formed. It does not mean anything in it is true.</p>
{rows}"""
    return render_page(
        title="Validation Rules", document_id="NET-SPEC-003", category="Specification / Validation",
        scope="Every structural check a copy must pass, stated in plain language",
        when_to_use="Checking a copy; re-implementing the validator; understanding a failed check",
        body=body, rel_path="spec/validation.html", owner=owner,
        eyebrow="MPLPB networked corpus · spec",
    )


def _write_log(root: Path, owner: str) -> None:
    (root / LOG_DIR).mkdir(parents=True, exist_ok=True)
    body = f"""<p>Append only. Entries are added, never edited or removed.</p>

<h2>Entries</h2>
<ul class="map">
{ENTRY_MARKER}
</ul>
"""
    (root / LOG_DIR / "revisions.html").write_text(
        render_page(
            title="Revision Log", document_id="NET-LOG-000", category="Log / Revisions",
            scope="Append-only record of changes and supersessions in this corpus",
            when_to_use="What changed and when; tracing a supersession", body=body,
            rel_path=f"{LOG_DIR}/revisions.html", owner=owner,
            eyebrow="MPLPB networked corpus · append-only",
            related=[("../index.html", "Back to the Main Index")],
        ),
        encoding="utf-8",
    )
    # revisions.html is the only page in _log/, so it needs a Sub-Index sibling
    # for rel="up" to resolve. Point up at the root instead.
    path = root / LOG_DIR / "revisions.html"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '<link rel="up" href="./_index.html">', '<link rel="up" href="../index.html">'
        ),
        encoding="utf-8",
    )


# ==========================================================================
# Growth inside a corpus: spokes, pages, supersession
# ==========================================================================

def add_spoke(root: Path, name: str, *, title: str, scope: str, when_to_use: str = "",
              owner: str = "", build: bool = True) -> Path:
    root = Path(root)
    name = slugify(name)
    spoke = root / name
    if spoke.exists():
        raise FileExistsError(f"spoke {name} already exists")
    spoke.mkdir(parents=True)
    corpus = Corpus(root)
    owner = owner or corpus.identity.get("owner", "")
    body = f"""<p><strong>Scope.</strong> {esc(scope)}</p>

<h2>Pages</h2>
<ul class="map">
{ENTRY_MARKER}
</ul>
"""
    (spoke / SUB_INDEX).write_text(
        render_page(
            title=title, document_id=f"{name.upper()}-INDEX", category="Navigator / Sub-Index",
            scope=scope, when_to_use=when_to_use or f"Broad questions about {title.lower()}",
            body=body, rel_path=f"{name}/{SUB_INDEX}", owner=owner,
            eyebrow="MPLPB networked corpus · sub-index",
            related=[("../index.html", "Back to the Main Index")],
        ),
        encoding="utf-8",
    )
    insert_entry(
        root / ROOT_PAGE,
        f'  <li><a href="{name}/_index.html">{esc(title)}</a>\n'
        f'    <span class="scope">scope: {esc(scope)}</span></li>',
    )
    bump_updated(root / ROOT_PAGE)
    corpus.log(f"{name.upper()}-INDEX spoke created at {name}/_index.html")
    if build:
        corpus.build()
    return spoke / SUB_INDEX


def _next_doc_id(corpus: Corpus, spoke: str) -> str:
    prefix = spoke.upper()
    used = [
        int(m.group(1))
        for p in corpus.pages().values()
        for m in [re.match(rf"^{re.escape(prefix)}-(\d+)", p.document_id)]
        if m
    ]
    return f"{prefix}-{(max(used) + 1) if used else 1:03d}"


def text_to_html(text: str) -> str:
    return "\n".join(f"<p>{esc(par.strip())}</p>" for par in re.split(r"\n\s*\n", text.strip()) if par.strip())


def add_page(
    root: Path,
    spoke: str,
    *,
    title: str,
    text: str,
    scope: str,
    when_to_use: str = "",
    origin: str = "human",
    origin_depth: int | None = None,
    derived_from: list[str] | None = None,
    ratified_by: str = "",
    document_id: str | None = None,
    owner: str = "",
    build: bool = True,
) -> Page:
    root = Path(root)
    corpus = Corpus(root)
    spoke = slugify(spoke)
    if not (root / spoke / SUB_INDEX).exists():
        raise FileNotFoundError(f"no spoke {spoke}; create it with add_spoke first")
    if origin not in pg.VALID_ORIGIN:
        raise ValueError(f"origin must be one of {pg.VALID_ORIGIN}")
    if origin == "ratified" and not ratified_by:
        raise ValueError("a ratified page must say who ratified it")
    derived_from = derived_from or []
    if origin_depth is None:
        origin_depth = derived_depth(corpus, derived_from) if origin == "machine" else 0
    document_id = document_id or _next_doc_id(corpus, spoke)
    rel = f"{spoke}/{slugify(title)}.html"
    if (root / rel).exists():
        raise FileExistsError(f"{rel} exists; supersede it instead of overwriting")
    extra = {"origin": origin, "origin-depth": str(origin_depth)}
    if derived_from:
        extra["derived-from"] = " ".join(derived_from)
    if origin == "ratified":
        extra["ratified-by"] = ratified_by
        extra["ratified-at"] = now_iso()
    (root / rel).write_text(
        render_page(
            title=title, document_id=document_id, category=f"{spoke.title()} / Page",
            scope=scope, when_to_use=when_to_use or scope, body=text_to_html(text),
            rel_path=rel, owner=owner or corpus.identity.get("owner", ""), extra_meta=extra,
        ),
        encoding="utf-8",
    )
    insert_entry(
        root / spoke / SUB_INDEX,
        f'  <li><a href="./{Path(rel).name}">{esc(title)}</a>\n'
        f'    <span class="scope">scope: {esc(scope)}</span></li>',
    )
    bump_updated(root / spoke / SUB_INDEX)
    corpus.log(f"{esc(document_id)} created at {esc(rel)} (origin {origin}, depth {origin_depth})")
    if build:
        corpus.build()
    return Page.load(root / rel, root)


def derived_depth(corpus: Corpus, refs: list[str]) -> int:
    """depth = 1 + max(depth of sources). Unknown remote sources are
    assumed to be machine-derived at depth 1 -- the conservative choice."""
    depths = []
    local = {p.document_id: p for p in corpus.pages().values() if p.status == "current"}
    for ref in refs:
        cid, did = split_ref(ref)
        if (not cid or cid == corpus.corpus_id) and did in local:
            depths.append(local[did].origin_depth)
        else:
            depths.append(1)
    return 1 + max(depths) if depths else 1


_HREF = re.compile(r'href="([^"]+)"')


def _extract_body(source: str) -> str:
    start = source.find("</dl></div>")
    end = source.find('<nav class="related">')
    if start < 0:
        return ""
    return source[start + len("</dl></div>"): end if end > 0 else source.find("</main>")].strip()


def _rebase(body: str, old_rel: str, new_rel: str) -> str:
    import os

    def fix(m):
        href = m.group(1)
        if not pg.is_internal(href) or pg.is_absolute(href):
            return m.group(0)
        target = os.path.normpath(os.path.join(os.path.dirname(old_rel), href))
        return f'href="{os.path.relpath(target, os.path.dirname(new_rel) or ".").replace(os.sep, "/")}"'

    return _HREF.sub(fix, body)


def supersede(root: Path, document_id: str, *, text: str, reason: str, title: str | None = None,
              scope: str | None = None, origin: str | None = None, ratified_by: str = "",
              build: bool = True) -> Page:
    """Replace a current page with a new version. The old version moves to
    _log/superseded/ as a retired page with its own ID; nothing is deleted."""
    root = Path(root)
    corpus = Corpus(root)
    old = corpus.find_current(document_id)
    if old is None:
        cid, did = split_ref(document_id)
        if cid and cid != corpus.corpus_id:
            raise PermissionError(
                f"{document_id} belongs to corpus {cid}; a corpus may only supersede its own "
                "documents (record diverges-from instead)"
            )
        raise KeyError(f"no current page {document_id}")
    if old.is_index:
        raise ValueError("indexes are appended to, not superseded")
    source = old.path.read_text(encoding="utf-8")
    version = old.version or 1
    retired_id = f"{document_id}-V{version}"
    retired_rel = f"{LOG_DIR}/{SUPERSEDED_DIR}/{old.path.stem}_v{version}.html"
    old_extra = {k[6:]: v for k, v in old.meta.items() if k[6:] in (
        "origin", "origin-depth", "derived-from", "ratified-by", "ratified-at")}
    (root / retired_rel).write_text(
        render_page(
            title=old.title, document_id=retired_id, category=old.get("category"),
            scope=old.scope, when_to_use=f"Provenance lookup only; superseded by {document_id}",
            body=_rebase(_extract_body(source), old.rel, retired_rel), rel_path=retired_rel,
            owner=old.get("owner"), status="retired", updated=old.updated,
            supersedes=old.get("supersedes"), extra_meta=old_extra,
            eyebrow="MPLPB networked corpus · retired",
            related=[("../../index.html", "Back to the Main Index")],
        ).replace('<link rel="up" href="./_index.html">', '<link rel="up" href="../revisions.html">'),
        encoding="utf-8",
    )
    new_origin = origin or old.origin
    extra = dict(old_extra)
    extra["origin"] = new_origin
    if new_origin == "ratified":
        if not ratified_by:
            raise ValueError("a ratified page must say who ratified it")
        extra.update({"ratified-by": ratified_by, "ratified-at": now_iso(), "origin-depth": "0"})
    elif new_origin == "human":
        extra["origin-depth"] = "0"
    old.path.write_text(
        render_page(
            title=title or old.title, document_id=document_id, category=old.get("category"),
            scope=scope or old.scope, when_to_use=old.get("when-to-use"), body=text_to_html(text),
            rel_path=old.rel, owner=old.get("owner"), updated=stamp(version + 1),
            supersedes=retired_id, extra_meta=extra,
        ),
        encoding="utf-8",
    )
    corpus.log(
        f"{esc(document_id)} supersedes {esc(retired_id)}; old version retired to "
        f"{esc(retired_rel)}. Reason: {esc(reason)}"
    )
    if build:
        corpus.build()
    return Page.load(old.path, root)
