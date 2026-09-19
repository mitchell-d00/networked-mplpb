"""
Routing -- scope is the routing primitive (§8).

The router answers one question: *where should an answer come from?* It
never produces the answer.

Every candidate corpus has declared a scope sentence and a list of scope
terms, each with synonyms from its vocabulary. A query is scored against
each candidate:

    2 points  per distinct query term matching a scope term or its synonym
    1 point   per distinct query term appearing in the scope sentence

This is deliberately not semantic similarity. It is *declared ownership*,
and it is only as good as the declarations. That is a real limitation, and
it is also what makes the router's decision inspectable: `explain()` shows
exactly which terms matched which declaration.

Outcomes:

    local       one corpus owns the query and this node carries it
    remote      one corpus owns the query and another node carries it
    ambiguous   several corpora score within `ownership_margin` of the
                leader and precedence does not resolve it -- report, do not merge
    not_found   nothing reaches `min_scope_score`

`unavailable` is not a routing outcome: it is what retrieval reports when the
owner is known but cannot be reached (see retrieve.py).

Hub corpora are never candidates. They say where to look; they do not own
questions (FM-N4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .node import Node
from .util import stem, terms


@dataclass
class Holder:
    node_id: str
    local: bool
    endpoints: list
    path: str
    held_as: str
    manifest_sha256: str
    via: str | None = None
    stale: bool = False
    verified: bool = True


@dataclass
class Candidate:
    corpus_id: str
    title: str
    scope: str
    scope_terms: list
    synonyms: dict
    relation: str
    seeded_from: dict | None
    holders: list = field(default_factory=list)
    score: float = 0.0
    matched: list = field(default_factory=list)

    @property
    def local(self) -> bool:
        return any(h.local for h in self.holders)

    def lineage_note(self) -> str:
        if self.seeded_from:
            return f"{self.relation} of {self.seeded_from.get('corpus_id')}"
        return self.relation


@dataclass
class Routing:
    query: str
    kind: str
    owner: Candidate | None = None
    contenders: list = field(default_factory=list)
    note: str = ""

    def explain(self) -> str:
        lines = [f"route: {self.kind}  — {self.note}"]
        for c in self.contenders:
            lines.append(
                f"  {c.score:>4.1f}  {c.corpus_id}  {c.title}  [{c.lineage_note()}]"
                f"  matched: {', '.join(c.matched) or '-'}"
            )
        return "\n".join(lines)


def candidates(node: Node) -> dict[str, Candidate]:
    out: dict[str, Candidate] = {}

    def add(entry: dict, holder: Holder):
        if entry.get("kind") == "hub":
            return
        cid = entry["corpus_id"]
        if cid not in out:
            out[cid] = Candidate(
                corpus_id=cid, title=entry["title"], scope=entry["scope"],
                scope_terms=entry["scope_terms"], synonyms=entry.get("synonyms", {}),
                relation=entry["relation"], seeded_from=entry.get("seeded_from"),
            )
        out[cid].holders.append(holder)

    own = node.description
    for entry in own["corpora"]:
        add(entry, Holder(node.node_id, True, own["retrieval"]["endpoints"], entry["path"],
                          entry.get("held_as", "origin"), entry["manifest_sha256"]))
    for desc, meta in node.known():
        for entry in desc.get("corpora", []):
            add(entry, Holder(desc["node_id"], False, desc.get("retrieval", {}).get("endpoints", []),
                              entry["path"], entry.get("held_as", "origin"), entry["manifest_sha256"],
                              via=meta.get("via"), stale=node.is_stale(meta),
                              verified=meta.get("verified", False)))
    for cand in out.values():
        # Local first, then fresh origin holders, then fresh mirrors, then stale.
        cand.holders.sort(key=lambda h: (not h.local, h.stale, h.held_as != "origin"))
    return out


def score(query: str, cand: Candidate) -> tuple[float, list]:
    q = set(terms(query))
    declared = {}
    for t in cand.scope_terms:
        for word in [t] + list(cand.synonyms.get(t, [])):
            for w in terms(word) or [stem(word.lower())]:
                declared.setdefault(w, t)
    prose = set(terms(cand.scope))
    total, matched = 0.0, []
    for w in sorted(q):
        if w in declared:
            total += 2
            matched.append(f"{w}->{declared[w]}")
        elif w in prose:
            total += 1
            matched.append(w)
    return total, matched


def route(node: Node, query: str) -> Routing:
    cfg = node.cfg
    cands = list(candidates(node).values())
    for c in cands:
        c.score, c.matched = score(query, c)
    cands.sort(key=lambda c: (-c.score, not c.local, c.corpus_id))
    live = [c for c in cands if c.score >= cfg["min_scope_score"]]
    shown = [c for c in cands if c.score > 0][:6]
    if not live:
        return Routing(query, "not_found", None, shown, "no known corpus declares this scope")
    top = live[0]
    close = [c for c in live if c.score * cfg["ownership_margin"] > top.score]
    if len(close) > 1:
        preferred = [c for c in close if c.corpus_id in cfg["precedence"]]
        if len(preferred) == 1:
            owner = preferred[0]
            return Routing(query, "local" if owner.local else "remote", owner, shown,
                           f"ambiguous between {len(close)} corpora; resolved by local precedence "
                           f"for {owner.corpus_id}")
        names = ", ".join(f"{c.corpus_id} ({c.lineage_note()})" for c in close)
        return Routing(query, "ambiguous", None, close,
                       f"several corpora plausibly own this and none has precedence: {names}")
    return Routing(query, "local" if top.local else "remote", top, shown,
                   f"{top.corpus_id} owns this by declared scope")
