"""
Nodes -- N_i = (ID_i, S_i, D_i).

A node is a directory on some machine:

    node.json              the signed discovery description D_i
    node.html              its human-readable twin
    config.json            local policy (see config.py)
    local/node.key          the Ed25519 secret; never served, never packed
    corpora/<corpus-id>/   the corpora S_i this node carries
    known/<node-id>.json   descriptions learned from peers and hubs
    cache/                 remote pages retrieved, with their envelopes

Identity. The node ID is derived from the node's public key:
`N-` + the first 16 hex digits of SHA-256(public key). A description is
accepted only if its signature verifies *and* its ID matches its key. Two
machines therefore cannot claim the same ID without one of them failing
verification -- identity collision becomes a detectable forgery rather than
a silent overwrite (FM-N14). Because keys live outside every corpus, copying
a corpus can never copy an identity.

The description answers the seven questions of §3: who are you, what corpora
do you carry, what scope does each claim, where is its boot artifact, how may
it be retrieved, when was this updated, and what other nodes do you know.
Nothing in it requires the node to reason.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfgmod
from . import ed25519
from .connectors import Unavailable, connect
from .corpus import Corpus, create_seed
from .page import esc, render_page
from .replicate import copy_corpus
from .util import PROTOCOL, canonical, now_iso, parse_iso, read_json, sha256_bytes, write_json

ROLES = ("node", "hub")


def node_id_for(public_hex: str) -> str:
    return "N-" + sha256_bytes(bytes.fromhex(public_hex))[:16].upper()


def unsigned(desc: dict) -> dict:
    return {k: v for k, v in desc.items() if k != "signature"}


def verify_description(desc: dict) -> tuple[bool, str]:
    try:
        pk = desc["public_key"]
        sig = bytes.fromhex(desc.get("signature", ""))
    except (KeyError, ValueError):
        return False, "missing or malformed key/signature"
    if node_id_for(pk) != desc.get("node_id"):
        return False, "node_id does not match public key (identity collision or forgery)"
    if not ed25519.verify(bytes.fromhex(pk), canonical(unsigned(desc)), sig):
        return False, "signature does not verify"
    return True, "ok"


def description_sha256(desc: dict) -> str:
    return sha256_bytes(canonical(desc))


class Node:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # -- lifecycle -----------------------------------------------------------
    @classmethod
    def init(cls, root: Path, name: str, role: str = "node") -> "Node":
        root = Path(root)
        if (root / "node.json").exists():
            raise FileExistsError(f"{root} is already a node")
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        for sub in ("local", "corpora", "known", "cache"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        secret = ed25519.new_secret()
        (root / "local" / "node.key").write_text(secret.hex() + "\n", encoding="utf-8")
        try:
            (root / "local" / "node.key").chmod(0o600)
        except OSError:
            pass
        write_json(root / "config.json", {"node_name": name})
        node = cls(root)
        write_json(root / "local" / "identity.json", {"name": name, "role": role})
        node.describe()
        return node

    @property
    def secret(self) -> bytes:
        return bytes.fromhex((self.root / "local" / "node.key").read_text().strip())

    @property
    def public_hex(self) -> str:
        return ed25519.public_key(self.secret).hex()

    @property
    def node_id(self) -> str:
        return node_id_for(self.public_hex)

    @property
    def meta(self) -> dict:
        return read_json(self.root / "local" / "identity.json")

    @property
    def name(self) -> str:
        return self.meta["name"]

    @property
    def role(self) -> str:
        return self.meta["role"]

    @property
    def cfg(self) -> dict:
        return cfgmod.load(self.root)

    @property
    def description(self) -> dict:
        return read_json(self.root / "node.json")

    def sign(self, obj: dict) -> str:
        return ed25519.sign(self.secret, canonical(obj)).hex()

    # -- corpora --------------------------------------------------------------
    def corpora(self) -> list[Corpus]:
        base = self.root / "corpora"
        return [Corpus(p) for p in sorted(base.iterdir()) if (p / "_net" / "corpus.json").exists()] if base.exists() else []

    def corpus(self, corpus_id: str) -> Corpus | None:
        for c in self.corpora():
            if c.corpus_id == corpus_id:
                return c
        return None

    def seed(self, **kw) -> Corpus:
        tmp = self.root / "corpora" / "_new_seed"
        cid = create_seed(tmp, **kw).corpus_id
        final = self.root / "corpora" / cid
        tmp.rename(final)
        self._held_as(cid, "origin")
        self.describe()
        return Corpus(final)

    def carry(self, src: Path, relation: str = "mirror", **kw) -> Corpus:
        """Copy a corpus onto this node. A mirror keeps its corpus ID; any
        other relation mints a new one."""
        tmp = self.root / "corpora" / "_incoming"
        if tmp.exists():
            shutil.rmtree(tmp)
        copy = copy_corpus(src, tmp, relation, **kw)
        cid = copy.corpus_id
        final = self.root / "corpora" / cid
        if final.exists():
            shutil.rmtree(tmp)
            raise FileExistsError(f"this node already carries corpus {cid}")
        tmp.rename(final)
        self._held_as(cid, "mirror" if relation == "mirror" else "origin")
        self.describe()
        return Corpus(final)

    def _held_as(self, corpus_id: str, held: str) -> None:
        path = self.root / "local" / "held.json"
        held_map = read_json(path) if path.exists() else {}
        held_map[corpus_id] = held
        write_json(path, held_map)

    def held_as(self, corpus_id: str) -> str:
        path = self.root / "local" / "held.json"
        return (read_json(path) if path.exists() else {}).get(corpus_id, "origin")

    # -- description -----------------------------------------------------------
    def describe(self, endpoints: list[str] | None = None) -> dict:
        """Rebuild and sign node.json from what is actually on disk."""
        prior = {}
        if (self.root / "node.json").exists():
            prior = read_json(self.root / "node.json")
        if endpoints is None:
            endpoints = prior.get("retrieval", {}).get("endpoints") or [self.root.as_uri()]
        entries = []
        for c in self.corpora():
            ident = c.identity
            vocab = c.vocabulary
            entries.append(
                {
                    "corpus_id": ident["corpus_id"],
                    "title": ident["title"],
                    "kind": ident.get("kind", "knowledge"),
                    "scope": ident["scope"],
                    "scope_terms": ident["scope_terms"],
                    "synonyms": {t: vocab.get(t, []) for t in ident["scope_terms"]},
                    "relation": ident["relation"],
                    "held_as": self.held_as(ident["corpus_id"]),
                    "seeded_from": ident.get("seeded_from"),
                    "manifest_sha256": c.manifest_sha256,
                    "path": f"corpora/{c.root.name}/",
                    "boot": f"corpora/{c.root.name}/index.html",
                }
            )
        known = []
        for desc, meta in self.known():
            known.append(
                {
                    "node_id": desc["node_id"],
                    "role": desc.get("role", "node"),
                    "endpoints": desc.get("retrieval", {}).get("endpoints", []),
                }
            )
        desc = {
            "protocol": PROTOCOL,
            "node_id": self.node_id,
            "name": self.name,
            "role": self.role,
            "public_key": self.public_hex,
            "corpora": entries,
            "retrieval": {"endpoints": endpoints, "layout": "static-files"},
            "updated": now_iso(),
            "known": known,
        }
        desc["signature"] = self.sign(desc)
        write_json(self.root / "node.json", desc)
        self._write_twin(desc)
        return desc

    def _write_twin(self, desc: dict) -> None:
        rows = "".join(
            f'  <li><a href="{esc(e["boot"])}">{esc(e["title"])}</a> <code>{esc(e["corpus_id"])}</code>'
            f' — {esc(e["relation"])}, held as {esc(e["held_as"])}'
            f'\n    <span class="scope">scope: {esc(e["scope"])}</span></li>\n'
            for e in desc["corpora"]
        )
        known = "".join(
            f"  <li><code>{esc(k['node_id'])}</code> ({esc(k['role'])}) {esc(', '.join(k['endpoints']))}</li>\n"
            for k in desc["known"]
        ) or "  <li>none yet</li>\n"
        body = f"""<p>Discovery description of this node. The authoritative copy is
<code>node.json</code>, which is signed; this page is its readable twin.</p>
<h2>Corpora carried</h2>
<ul class="map">
{rows or '  <li>none</li>'}
</ul>
<h2>Known nodes</h2>
<ul class="map">
{known}</ul>
<h2>Retrieval</h2>
<p>Static files. Endpoints: {esc(', '.join(desc['retrieval']['endpoints']))}</p>
"""
        html_text = render_page(
            title=f"Node {desc['name']}", document_id=desc["node_id"], category="Node / Description",
            scope="Which corpora this machine carries and how to reach them",
            when_to_use="Discovering this node", body=body, rel_path="index.html",
            eyebrow=f"MPLPB node · {desc['role']}", related=[],
            extra_meta={"node-id": desc["node_id"], "public-key": desc["public_key"]},
        ).replace('<link rel="stylesheet" href="style.css">', "")
        (self.root / "node.html").write_text(html_text, encoding="utf-8")

    # -- discovery -------------------------------------------------------------
    def known(self) -> list[tuple[dict, dict]]:
        out = []
        base = self.root / "known"
        if not base.exists():
            return out
        for path in sorted(base.glob("N-*.json")):
            if path.name.endswith(".meta.json"):
                continue
            meta_path = path.with_name(path.stem + ".meta.json")
            out.append((read_json(path), read_json(meta_path) if meta_path.exists() else {}))
        return out

    def known_by_id(self, node_id: str) -> tuple[dict, dict] | None:
        for desc, meta in self.known():
            if desc["node_id"] == node_id:
                return desc, meta
        return None

    def _accept(self, desc: dict, *, via: str | None, endpoint: str | None, last_seen: str | None = None) -> str:
        cfg = self.cfg
        ok, why = verify_description(desc)
        if not ok:
            self._record_collision(desc, why)
            if cfg["verify"] == "require":
                raise Unavailable(f"rejected description {desc.get('node_id')}: {why}")
        if desc.get("node_id") == self.node_id:
            return "self"
        existing = self.known_by_id(desc["node_id"])
        if existing and existing[0].get("updated", "") > desc.get("updated", "") and via:
            # A hub's copy is older than one we already hold; keep ours.
            return "kept-newer"
        write_json(self.root / "known" / f"{desc['node_id']}.json", desc)
        write_json(
            self.root / "known" / f"{desc['node_id']}.meta.json",
            {
                "last_seen": last_seen or now_iso(),
                "via": via,
                "endpoint": endpoint,
                "verified": ok,
                "verify_note": why,
            },
        )
        return "learned"

    def _record_collision(self, desc: dict, why: str) -> None:
        path = self.root / "known" / "collisions.json"
        items = read_json(path) if path.exists() else []
        items.append({"node_id": desc.get("node_id"), "public_key": desc.get("public_key"), "reason": why, "at": now_iso()})
        write_json(path, items)

    def learn(self, endpoint: str, *, hops: int | None = None, via: str | None = None) -> list[str]:
        """Read a node's description at `endpoint`. If it is a hub, also read
        its registry and learn every description in it (verified one by one),
        following hub-to-hub links up to max_hops."""
        cfg = self.cfg
        hops = cfg["max_hops"] if hops is None else hops
        conn = connect(endpoint, cfg)
        desc = conn.read_json("node.json")
        learned = []
        status = self._accept(desc, via=via, endpoint=endpoint)
        if status == "learned":
            learned.append(desc["node_id"])
        if desc.get("role") == "hub":
            for entry in desc.get("corpora", []):
                if entry.get("kind") != "hub":
                    continue
                try:
                    registry = conn.read_json(entry["path"] + "nodes/registry.json")
                except Unavailable:
                    continue
                for item in registry.get("entries", []):
                    sub = item["description"]
                    try:
                        st = self._accept(sub, via=desc["node_id"], endpoint=None, last_seen=item.get("last_seen"))
                    except Unavailable:
                        continue
                    if st == "learned":
                        learned.append(sub["node_id"])
                    if sub.get("role") == "hub" and hops > 0:
                        for ep in sub.get("retrieval", {}).get("endpoints", []):
                            try:
                                learned += self.learn(ep, hops=hops - 1, via=desc["node_id"])
                                break
                            except Unavailable:
                                continue
        self.describe()
        return learned

    def forget(self, node_id: str) -> None:
        for suffix in (".json", ".meta.json"):
            p = self.root / "known" / f"{node_id}{suffix}"
            if p.exists():
                p.unlink()
        self.describe()

    def is_stale(self, meta: dict) -> bool:
        seen = meta.get("last_seen")
        if not seen:
            return True
        age = datetime.now(timezone.utc) - parse_iso(seen)
        return age.total_seconds() > self.cfg["stale_after_days"] * 86400

    def refresh(self) -> dict:
        """Re-read every known node from its own endpoints. Unreachable nodes
        keep their old description and simply age toward staleness."""
        result = {}
        for desc, meta in self.known():
            ok = False
            for ep in desc.get("retrieval", {}).get("endpoints", []):
                try:
                    fresh = connect(ep, self.cfg).read_json("node.json")
                    self._accept(fresh, via=None, endpoint=ep)
                    ok = True
                    break
                except Unavailable:
                    continue
            result[desc["node_id"]] = "refreshed" if ok else "unreachable"
        self.describe()
        return result
