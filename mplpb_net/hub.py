"""
Hubs -- H = {D_1, ..., D_n}: a corpus of corpus descriptions.

A hub is an ordinary node whose one special corpus has kind "hub". Each
registered node gets a page `nodes/<node-id>.html` holding its signed
description verbatim, and `nodes/registry.json` lists them all. Because the
hub corpus is an ordinary MPLPB corpus it validates, copies, mirrors, and
survives by exactly the same mechanism as everything it indexes (§6).

What a hub does:     answer "where should I look?"
What a hub does not: store corpora, answer questions, embed, rank by
                     quality, summarize, reconcile, or adjudicate.

There is deliberately no function in this module that takes a query and
returns content. Routing reads the registry; retrieval goes to the node that
carries the corpus. A hub that grew such a function would be hub capture
(FM-N4), and it would show up in this file's diff.

A hub cannot forge a description -- each one is signed by the node it
describes, and nodes verify them one by one on the way in. A hub can omit
descriptions, or keep dead ones. The first is visible only by comparing
hubs; the second is handled by `last_seen` and staleness (FM-N5).
"""

from __future__ import annotations

import json
from pathlib import Path

from .connectors import Unavailable, connect
from .corpus import Corpus, supersede, text_to_html
from .node import Node, verify_description
from .page import ENTRY_MARKER, SUB_INDEX, bump_updated, esc, insert_entry, render_page
from .util import now_iso, read_json, write_json


def init_hub(root: Path, name: str, *, owner: str = "") -> Node:
    node = Node.init(root, name, role="hub")
    node.seed(
        title=f"Hub {name}",
        scope="Discovery descriptions of other nodes and hubs",
        scope_terms=["discovery", "registry"],
        owner=owner,
        description=(
            f"A hub corpus maintained by {name}. It lists signed descriptions of other "
            "nodes so a reader can find where to look. It does not contain their corpora "
            "and does not answer their questions."
        ),
        kind="hub",
    )
    _write_registry(node)
    return node


def hub_corpus(node: Node) -> Corpus:
    for c in node.corpora():
        if c.identity.get("kind") == "hub":
            return c
    raise ValueError(f"{node.root} carries no hub corpus")


def _page_for(desc: dict) -> tuple[str, str]:
    lines = "".join(
        f"  <li><code>{esc(e['corpus_id'])}</code> {esc(e['title'])} — {esc(e['relation'])}"
        f"\n    <span class=\"scope\">scope: {esc(e['scope'])}</span></li>\n"
        for e in desc.get("corpora", [])
    )
    body = f"""<p>Signed discovery description of node <code>{esc(desc['node_id'])}</code>
({esc(desc.get('name', ''))}), copied verbatim. This hub vouches for nothing in
it: verify the signature, then go to the node.</p>
<h2>Corpora</h2>
<ul class="map">
{lines}</ul>
<h2>Endpoints</h2>
<p>{esc(', '.join(desc.get('retrieval', {}).get('endpoints', [])))}</p>
<h2>Description</h2>
<pre>{esc(json.dumps(desc, indent=2, sort_keys=True))}</pre>
"""
    scope = f"Where node {desc['node_id']} can be found and which corpora it declares"
    return body, scope


def register(hub: Node, endpoint: str) -> str:
    """Fetch, verify, and record a node's description. Re-registering an
    already-known node supersedes its page rather than overwriting it."""
    conn = connect(endpoint, hub.cfg)
    desc = conn.read_json("node.json")
    ok, why = verify_description(desc)
    if not ok:
        raise Unavailable(f"refusing to register {desc.get('node_id')}: {why}")
    return _record(hub, desc)


def register_description(hub: Node, desc: dict) -> str:
    ok, why = verify_description(desc)
    if not ok:
        raise Unavailable(f"refusing to register {desc.get('node_id')}: {why}")
    return _record(hub, desc)


def _record(hub: Node, desc: dict) -> str:
    corpus = hub_corpus(hub)
    nid = desc["node_id"]
    rel = f"nodes/{nid.lower()}.html"
    body, scope = _page_for(desc)
    doc_id = f"HUB-{nid}"
    stored = corpus.root / "nodes" / "descriptions"
    stored.mkdir(parents=True, exist_ok=True)
    existing = corpus.find_current(doc_id)
    if existing is not None:
        prior = read_json(stored / f"{nid}.json")
        if prior == desc:
            _touch(corpus, nid)
            _write_registry(hub)
            return "unchanged"
        write_json(stored / f"{nid}.json", desc)
        supersede(corpus.root, doc_id, text="", reason="node re-registered with a newer description", build=False)
        # supersede() writes a text body; replace it with the rendered description.
        page = corpus.root / rel
        src = page.read_text(encoding="utf-8")
        start, end = src.find("</dl></div>") + len("</dl></div>"), src.find('<nav class="related">')
        page.write_text(src[:start] + "\n\n" + body + "\n" + src[end:], encoding="utf-8")
        status = "updated"
    else:
        write_json(stored / f"{nid}.json", desc)
        (corpus.root / rel).write_text(
            render_page(
                title=f"Node {desc.get('name', nid)}", document_id=doc_id,
                category="Hub / Description", scope=scope,
                when_to_use="Finding where a corpus lives; checking a node's declared scope",
                body=body, rel_path=rel, owner=corpus.identity.get("owner", ""),
                eyebrow="MPLPB hub · description",
            ),
            encoding="utf-8",
        )
        insert_entry(
            corpus.root / "nodes" / SUB_INDEX,
            f'  <li><a href="./{nid.lower()}.html">{esc(desc.get("name", nid))}</a> <code>{esc(nid)}</code>\n'
            f'    <span class="scope">scope: {esc(scope)}</span></li>',
        )
        bump_updated(corpus.root / "nodes" / SUB_INDEX)
        corpus.log(f"{esc(doc_id)} registered at {esc(rel)}")
        status = "registered"
    _touch(corpus, nid)
    _write_registry(hub)
    return status


def _touch(corpus: Corpus, nid: str) -> None:
    path = corpus.root / "nodes" / "last_seen.json"
    seen = read_json(path) if path.exists() else {}
    seen[nid] = now_iso()
    write_json(path, seen)


def _write_registry(hub: Node) -> None:
    corpus = hub_corpus(hub)
    stored = corpus.root / "nodes" / "descriptions"
    seen_path = corpus.root / "nodes" / "last_seen.json"
    seen = read_json(seen_path) if seen_path.exists() else {}
    entries = []
    if stored.exists():
        for p in sorted(stored.glob("N-*.json")):
            desc = read_json(p)
            entries.append({"node_id": desc["node_id"], "role": desc.get("role", "node"),
                            "last_seen": seen.get(desc["node_id"]), "description": desc})
    write_json(corpus.root / "nodes" / "registry.json",
               {"hub": hub.node_id, "generated": now_iso(), "entries": entries})
    corpus.build()
    hub.describe()


def refresh(hub: Node) -> dict:
    """Re-fetch every registered node from its own endpoints. Nodes that do
    not answer keep their last description and their old last_seen, so the
    registry exposes staleness instead of hiding it."""
    corpus = hub_corpus(hub)
    out = {}
    stored = corpus.root / "nodes" / "descriptions"
    for p in sorted(stored.glob("N-*.json")) if stored.exists() else []:
        desc = read_json(p)
        out[desc["node_id"]] = "unreachable"
        for ep in desc.get("retrieval", {}).get("endpoints", []):
            try:
                out[desc["node_id"]] = register(hub, ep)
                break
            except Unavailable:
                continue
    return out


def rebuild(root: Path, name: str, sources: list[Path], *, owner: str = "") -> tuple[Node, int]:
    """Reconstruct a hub from descriptions that survive on other nodes.
    Signed descriptions verify wherever they were found, so a hub rebuilt
    from copies is as trustworthy as the original (§26)."""
    hub = init_hub(root, name, owner=owner)
    count = 0
    seen = set()
    for src in sources:
        node = Node(src)
        candidates = [node.description] + [d for d, _ in node.known()]
        for desc in candidates:
            if desc["node_id"] in seen or desc.get("role") == "hub":
                continue
            ok, _ = verify_description(desc)
            if ok:
                register_description(hub, desc)
                seen.add(desc["node_id"])
                count += 1
    return hub, count
