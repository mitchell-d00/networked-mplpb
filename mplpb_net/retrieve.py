"""
Retrieval and provenance -- provenance must survive the trip (§10).

Retrieval is static: a node only has to serve files. The reader fetches the
serving node's signed description, the corpus manifest, and the corpus
catalog, ranks the catalog locally, and fetches one page. Every hop is
checked against the one before it:

    description   signature verifies; node ID matches key
    manifest      its hash equals the fingerprint in the signed description
    catalog       its hash is listed in the manifest
    page          its hash is listed in the manifest

So the provenance of a page reduces to a signature by the node that served
it, over a description that names the corpus fingerprint, which names the
page hash. Nothing in that chain depends on trusting a hub, a relay, or a
cache. `verify_envelope()` repeats the chain for any third party holding the
same four artifacts.

    Transport is not authorship.   route records hops, never authors
    Discovery is not authority.    a hub appears in route as "discovery"
    Caching is not authorship.     a cache adds an attestation, not a source
    Reasoning is not provenance.   nothing here generates text
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .connectors import Unavailable, connect
from .corpus import Corpus
from .node import Node, description_sha256, unsigned, verify_description
from .router import Candidate, Holder, Routing, route
from .util import canonical, now_iso, read_json, sha256_bytes, terms, write_json
from . import ed25519


@dataclass
class Answer:
    query: str
    kind: str  # local | remote | ambiguous | not_found | unavailable
    routing: Routing
    envelope: dict | None = None
    text: str = ""
    withheld: int = 0
    tried: list = field(default_factory=list)
    cached: dict | None = None
    note: str = ""

    def render(self) -> str:
        out = []
        if self.kind in ("local", "remote") and self.envelope:
            e = self.envelope
            out.append(e["title"])
            out.append("")
            out.append("  " + (self.text[:700] + ("…" if len(self.text) > 700 else "")))
            out.append("")
            out.append(
                f"  [{e['corpus_id']}:{e['document_id']} · {e['path']} · v{e['version']} · "
                f"{e['status']} · origin {e['origin']} d{e['origin_depth']}]"
            )
            out.append(f"  served by {e['served_by']['node_id']}  verified={e['verified']}")
            out.append("  route: " + " -> ".join(f"{h['node_id']}({h['role']})" for h in e["route"]))
        elif self.kind == "ambiguous":
            out.append("Ambiguous: more than one corpus declares this scope. Not merging them.")
            for c in self.routing.contenders:
                out.append(f"  {c.corpus_id}  {c.title}  [{c.lineage_note()}]  score {c.score:.1f}")
            out.append("  Narrow the question, or set `precedence` in config.json.")
        elif self.kind == "not_found":
            out.append("Not found in the known network.")
            out.append("  No corpus this node knows about declares a scope that owns this question.")
        elif self.kind == "unavailable":
            owner = self.routing.owner
            out.append(f"Relevant corpus known; node unavailable. ({owner.corpus_id} {owner.title})")
            for holder, err in self.tried:
                out.append(f"  tried {holder}: {err}")
            if self.cached:
                c = self.cached
                out.append(
                    f"  A cached copy exists ({c['corpus_id']}:{c['document_id']} v{c['version']}, "
                    f"retrieved {c['retrieved_at']} from {c['served_by']['node_id']}). "
                    "It is a copy, not an answer from the owner."
                )
        if self.withheld:
            out.append(f"  ({self.withheld} matching page(s) withheld by local d_max policy)")
        if self.note:
            out.append(f"  note: {self.note}")
        return "\n".join(out)


# --------------------------------------------------------------------------
# Ranking inside one corpus
# --------------------------------------------------------------------------

def rank(documents: list[dict], query: str, cfg: dict) -> tuple[list[tuple[float, dict]], int]:
    q = terms(query)
    if not q:
        return [], 0
    fields = []
    for doc in documents:
        bag = Counter()
        for weight, text in ((3, doc.get("title")), (2, doc.get("scope")),
                             (2, doc.get("when_to_use")), (1, doc.get("text"))):
            for t in terms(text or ""):
                bag[t] += weight
        fields.append(bag)
    n = len(documents)
    df = Counter(t for bag in fields for t in set(bag))
    scored, withheld = [], 0
    for doc, bag in zip(documents, fields):
        s = sum(math.log(1 + bag[t]) * math.log(1 + n / (1 + df[t])) for t in set(q) if bag[t])
        if s <= 0:
            continue
        if doc.get("is_index"):
            s *= 0.5
        if doc.get("status") != "current" and not cfg["include_retired"]:
            continue
        if int(doc.get("origin_depth", 0)) > cfg["d_max"]:
            withheld += 1
            continue
        scored.append((s, doc))
    scored.sort(key=lambda x: -x[0])
    return scored, withheld


# --------------------------------------------------------------------------
# Envelopes
# --------------------------------------------------------------------------

def make_envelope(*, cand: Candidate, doc: dict, served: dict, endpoint: str, manifest_sha: str,
                  route_hops: list, verified: bool, steps: list, corpus_title: str) -> dict:
    return {
        "corpus_id": cand.corpus_id,
        "corpus_title": corpus_title,
        "document_id": doc["document_id"],
        "path": doc["path"],
        "title": doc["title"],
        "version": doc["version"],
        "status": doc["status"],
        "origin": doc["origin"],
        "origin_depth": doc["origin_depth"],
        "ratified_by": doc.get("ratified_by", ""),
        "content_sha256": doc["sha256"],
        "manifest_sha256": manifest_sha,
        "served_by": {
            "node_id": served["node_id"],
            "public_key": served["public_key"],
            "description_sha256": description_sha256(served),
            "endpoint": endpoint,
        },
        "route": route_hops,
        "retrieved_at": now_iso(),
        "verified": verified,
        "verification": steps,
        "attestations": [],
    }


def verify_envelope(envelope: dict, page: bytes, manifest: dict, description: dict) -> tuple[bool, str]:
    """Re-check an envelope from its four artifacts. Anyone can run this."""
    ok, why = verify_description(description)
    if not ok:
        return False, f"description: {why}"
    if description_sha256(description) != envelope["served_by"]["description_sha256"]:
        return False, "description is not the one the envelope names"
    entry = next((e for e in description["corpora"] if e["corpus_id"] == envelope["corpus_id"]), None)
    if entry is None:
        return False, "serving node does not declare this corpus"
    if entry["manifest_sha256"] != envelope["manifest_sha256"]:
        return False, "fingerprint in envelope differs from signed description"
    if sha256_bytes(canonical(manifest["files"])) != envelope["manifest_sha256"]:
        return False, "manifest does not hash to the fingerprint"
    if manifest["files"].get(envelope["path"]) != envelope["content_sha256"]:
        return False, "page hash not listed in manifest"
    if sha256_bytes(page) != envelope["content_sha256"]:
        return False, "page bytes do not match"
    for att in envelope.get("attestations", []):
        body = {k: v for k, v in envelope.items() if k != "attestations"}
        if not ed25519.verify(bytes.fromhex(att["public_key"]), canonical(body), bytes.fromhex(att["signature"])):
            return False, f"attestation by {att['node_id']} does not verify"
    return True, "ok"


# --------------------------------------------------------------------------
# Asking
# --------------------------------------------------------------------------

def _fetch_from(node: Node, cand: Candidate, holder: Holder, query: str, cfg: dict):
    """Try one holder. Returns (envelope, text, withheld, artifacts) or raises Unavailable."""
    last = None
    for endpoint in holder.endpoints or []:
        try:
            conn = connect(endpoint, cfg)
            steps = []
            served = conn.read_json("node.json")
            ok, why = verify_description(served)
            if served.get("node_id") != holder.node_id:
                raise Unavailable(f"endpoint now answers as {served.get('node_id')}, not {holder.node_id}")
            steps.append(f"description signature: {why}")
            entry = next((e for e in served["corpora"] if e["corpus_id"] == cand.corpus_id), None)
            if entry is None:
                raise Unavailable(f"{holder.node_id} no longer carries {cand.corpus_id}")
            manifest = conn.read_json(entry["path"] + "_net/manifest.json")
            fp = sha256_bytes(canonical(manifest["files"]))
            ok = ok and fp == entry["manifest_sha256"]
            steps.append(f"manifest fingerprint matches description: {fp == entry['manifest_sha256']}")
            cat_bytes = conn.read(entry["path"] + "_net/catalog.json")
            cat_ok = manifest["files"].get("_net/catalog.json") == sha256_bytes(cat_bytes)
            ok = ok and cat_ok
            steps.append(f"catalog listed in manifest: {cat_ok}")
            import json as _json
            catalog = _json.loads(cat_bytes.decode("utf-8"))
            ranked, withheld = rank(catalog["documents"], query, cfg)
            if not ranked:
                return None, "", withheld, None
            doc = ranked[0][1]
            page = conn.read(entry["path"] + doc["path"])
            page_ok = sha256_bytes(page) == doc["sha256"] == manifest["files"].get(doc["path"])
            ok = ok and page_ok
            steps.append(f"page listed in manifest: {page_ok}")
            if not ok and cfg["verify"] == "require":
                raise Unavailable("verification failed: " + "; ".join(steps))
            if cfg["verify"] == "off":
                steps.append("verification disabled by config")
            hops = [{"node_id": node.node_id, "role": "requester"}]
            if holder.via:
                hops.append({"node_id": holder.via, "role": "discovery"})
            hops.append({"node_id": holder.node_id, "role": "server"})
            env = make_envelope(cand=cand, doc=doc, served=served, endpoint=endpoint,
                                manifest_sha=fp, route_hops=hops, verified=ok, steps=steps,
                                corpus_title=cand.title)
            return env, doc.get("text", ""), withheld, (page, manifest, served)
        except Unavailable as exc:
            last = exc
            continue
    raise Unavailable(str(last) if last else "no endpoints")


def _local(node: Node, cand: Candidate, query: str, cfg: dict):
    corpus = node.corpus(cand.corpus_id)
    catalog = read_json(corpus.root / "_net" / "catalog.json")
    ranked, withheld = rank(catalog["documents"], query, cfg)
    if not ranked:
        return None, "", withheld
    doc = ranked[0][1]
    page = (corpus.root / doc["path"]).read_bytes()
    manifest = corpus.manifest
    served = node.description
    fp = sha256_bytes(canonical(manifest["files"]))
    ok = (sha256_bytes(page) == manifest["files"].get(doc["path"])
          and verify_description(served)[0]
          and any(e["corpus_id"] == cand.corpus_id and e["manifest_sha256"] == fp for e in served["corpora"]))
    env = make_envelope(cand=cand, doc=doc, served=served, endpoint="local", manifest_sha=fp,
                        route_hops=[{"node_id": node.node_id, "role": "server"}],
                        verified=ok, steps=["local artifacts checked against manifest"],
                        corpus_title=cand.title)
    return env, doc.get("text", ""), withheld


def cache_path(node: Node, corpus_id: str, path: str) -> Path:
    return node.root / "cache" / corpus_id / path


def _store(node: Node, env: dict, artifacts) -> None:
    page, manifest, served = artifacts
    body = {k: v for k, v in env.items() if k != "attestations"}
    env["attestations"] = [{
        "node_id": node.node_id, "role": "cache", "public_key": node.public_hex,
        "signature": node.sign(body),
        "meaning": "this node relayed and stored these bytes; it did not author them",
    }]
    target = cache_path(node, env["corpus_id"], env["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(page)
    write_json(target.with_name(target.name + ".envelope.json"), env)
    base = node.root / "cache" / "_artifacts"
    write_json(base / f"manifest-{env['manifest_sha256'][:24]}.json", manifest)
    write_json(base / f"description-{env['served_by']['description_sha256'][:24]}.json", served)


def cached_envelopes(node: Node, corpus_id: str | None = None) -> list[tuple[Path, dict]]:
    base = node.root / "cache"
    out = []
    for p in sorted(base.rglob("*.envelope.json")) if base.exists() else []:
        env = read_json(p)
        if corpus_id is None or env["corpus_id"] == corpus_id:
            out.append((p, env))
    return out


def ask(node: Node, query: str) -> Answer:
    cfg = node.cfg
    routing = route(node, query)
    if routing.kind in ("ambiguous", "not_found"):
        return Answer(query, routing.kind, routing)
    cand = routing.owner
    tried = []
    for holder in cand.holders:
        if holder.local:
            env, text, withheld = _local(node, cand, query, cfg)
            if env is None:
                return Answer(query, "not_found", routing, withheld=withheld,
                              note=f"{cand.corpus_id} owns this scope but no page matched")
            return Answer(query, "local", routing, env, text, withheld, note=routing.note)
        try:
            env, text, withheld, artifacts = _fetch_from(node, cand, holder, query, cfg)
        except Unavailable as exc:
            tried.append((holder.node_id + (" (stale)" if holder.stale else ""), str(exc)))
            continue
        if env is None:
            return Answer(query, "not_found", routing, withheld=withheld,
                          note=f"{cand.corpus_id} owns this scope but no page matched")
        note = routing.note
        if holder.held_as == "mirror":
            note += f"; served by a mirror ({holder.node_id}) of {cand.corpus_id}"
        if cfg["cache_remote"]:
            _store(node, env, artifacts)
        return Answer(query, "remote", routing, env, text, withheld, tried=tried, note=note)
    cached = next((e for _, e in cached_envelopes(node, cand.corpus_id)), None)
    return Answer(query, "unavailable", routing, tried=tried, cached=cached)


def refresh_cache(node: Node) -> list[dict]:
    """Learn about supersession of cached pages without deleting them (§14).
    A cached page whose document has moved on is marked, not removed."""
    changes = []
    cands = None
    from .router import candidates

    cands = candidates(node)
    for path, env in cached_envelopes(node):
        cand = cands.get(env["corpus_id"])
        if cand is None:
            continue
        for holder in cand.holders:
            if holder.local:
                continue
            try:
                for ep in holder.endpoints:
                    conn = connect(ep, node.cfg)
                    served = conn.read_json("node.json")
                    entry = next(e for e in served["corpora"] if e["corpus_id"] == env["corpus_id"])
                    catalog = conn.read_json(entry["path"] + "_net/catalog.json")
                    current = next((d for d in catalog["documents"]
                                    if d["document_id"] == env["document_id"] and d["status"] == "current"), None)
                    if current and current["version"] != env["version"]:
                        # A sidecar, not an edit: the envelope is signed and stays as retrieved.
                        write_json(path.with_name(path.name.replace(".envelope.json", ".remote-status.json")),
                                   {"superseded_remotely": True, "by_version": current["version"],
                                    "seen_at": now_iso(), "supersedes": current["supersedes"]})
                        changes.append({"document_id": env["document_id"], "cached_version": env["version"],
                                        "current_version": current["version"]})
                    break
                break
            except (Unavailable, StopIteration):
                continue
    return changes
