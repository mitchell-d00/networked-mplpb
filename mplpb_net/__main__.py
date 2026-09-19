"""
mplpb-net -- command line for Networked MPLPB.

    corpus    seed | validate | build | spoke | add | supersede | copy | pack | unpack
    node      init | seed | carry | describe | learn | refresh | known | forget
    hub       init | register | refresh | rebuild
    query     route | ask | cache-refresh
    serve     serve a node's public files over HTTP
    config    show | set | check | explain
    experiment / scale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import config as cfgmod
from . import hub as hubmod
from .corpus import Corpus, add_page, add_spoke, create_seed, supersede
from .node import Node
from .replicate import copy_corpus, pack, unpack
from .retrieve import ask, refresh_cache
from .router import route
from .validate import validate


def _terms(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


def _vocab(raw: list[str] | None) -> dict:
    out = {}
    for item in raw or []:
        term, _, syns = item.partition(":")
        out[term.strip()] = _terms(syns)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mplpb-net", description="Networked MPLPB: grow a knowledge network from a seed.")
    p.add_argument("--version", action="version", version=f"mplpb-net {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="create a new seed corpus")
    s.add_argument("dir")
    s.add_argument("--title", required=True)
    s.add_argument("--scope", required=True)
    s.add_argument("--terms", required=True, help="comma-separated scope terms")
    s.add_argument("--owner", default="")
    s.add_argument("--description", default="")
    s.add_argument("--synonym", action="append", help="term:syn1,syn2 (repeatable)")

    s = sub.add_parser("validate", help="run the 16 structural checks; exit 1 on failure")
    s.add_argument("dir")

    s = sub.add_parser("build", help="regenerate catalog, twin, and manifest after hand edits")
    s.add_argument("dir")

    s = sub.add_parser("spoke", help="add a bounded spoke to a corpus")
    s.add_argument("dir")
    s.add_argument("name")
    s.add_argument("--title", required=True)
    s.add_argument("--scope", required=True)

    s = sub.add_parser("add", help="add a page to a spoke")
    s.add_argument("dir")
    s.add_argument("spoke")
    s.add_argument("--title", required=True)
    s.add_argument("--scope", required=True)
    s.add_argument("--text", required=True, help="page text, or @file to read it")
    s.add_argument("--when", default="")
    s.add_argument("--origin", default="human", choices=["human", "machine", "ratified"])
    s.add_argument("--depth", type=int)
    s.add_argument("--derived-from", default="", help="space-separated refs, e.g. C-ABC:DOC-1")
    s.add_argument("--ratified-by", default="")

    s = sub.add_parser("supersede", help="replace a page, retiring the old version")
    s.add_argument("dir")
    s.add_argument("document_id")
    s.add_argument("--text", required=True)
    s.add_argument("--reason", required=True)
    s.add_argument("--origin", choices=["human", "machine", "ratified"])
    s.add_argument("--ratified-by", default="")

    s = sub.add_parser("copy", help="replicate a corpus and declare the relation")
    s.add_argument("src")
    s.add_argument("dst")
    s.add_argument("--relation", default="mirror", choices=["mirror", "descendant", "fork", "partial"])
    s.add_argument("--title")
    s.add_argument("--scope")
    s.add_argument("--terms")
    s.add_argument("--synonym", action="append")
    s.add_argument("--spokes", help="comma-separated spokes to keep (partial)")

    s = sub.add_parser("pack", help="write a corpus or node into a ZIP (keys excluded)")
    s.add_argument("src")
    s.add_argument("archive")
    s = sub.add_parser("unpack", help="extract a ZIP")
    s.add_argument("archive")
    s.add_argument("dst")

    node = sub.add_parser("node", help="node operations").add_subparsers(dest="ncmd", required=True)
    n = node.add_parser("init")
    n.add_argument("dir")
    n.add_argument("--name", required=True)
    n = node.add_parser("seed", help="create a seed directly on this node")
    n.add_argument("dir")
    n.add_argument("--title", required=True)
    n.add_argument("--scope", required=True)
    n.add_argument("--terms", required=True)
    n.add_argument("--owner", default="")
    n.add_argument("--synonym", action="append")
    n = node.add_parser("carry", help="copy a corpus onto this node")
    n.add_argument("dir")
    n.add_argument("src")
    n.add_argument("--relation", default="mirror", choices=["mirror", "descendant", "fork", "partial"])
    n.add_argument("--title")
    n.add_argument("--scope")
    n.add_argument("--terms")
    n.add_argument("--synonym", action="append")
    n.add_argument("--spokes")
    n = node.add_parser("describe", help="rebuild and sign node.json")
    n.add_argument("dir")
    n.add_argument("--endpoint", action="append", help="where others can reach this node (repeatable)")
    n = node.add_parser("learn", help="learn a node or hub by endpoint")
    n.add_argument("dir")
    n.add_argument("endpoint")
    n = node.add_parser("refresh", help="re-read every known node")
    n.add_argument("dir")
    n = node.add_parser("known", help="list known nodes")
    n.add_argument("dir")
    n = node.add_parser("forget")
    n.add_argument("dir")
    n.add_argument("node_id")

    hub = sub.add_parser("hub", help="hub operations").add_subparsers(dest="hcmd", required=True)
    h = hub.add_parser("init")
    h.add_argument("dir")
    h.add_argument("--name", required=True)
    h.add_argument("--owner", default="")
    h = hub.add_parser("register")
    h.add_argument("dir")
    h.add_argument("endpoint")
    h = hub.add_parser("refresh")
    h.add_argument("dir")
    h = hub.add_parser("rebuild", help="rebuild a hub from descriptions surviving on nodes")
    h.add_argument("dir")
    h.add_argument("--name", required=True)
    h.add_argument("--from", dest="sources", action="append", required=True)

    s = sub.add_parser("route", help="where should this be answered? (never answers)")
    s.add_argument("dir")
    s.add_argument("query")
    s = sub.add_parser("ask", help="route, retrieve, and cite with a provenance envelope")
    s.add_argument("dir")
    s.add_argument("query")
    s.add_argument("--json", action="store_true", help="print the envelope")
    s = sub.add_parser("cache-refresh", help="learn which cached pages were superseded remotely")
    s.add_argument("dir")

    s = sub.add_parser("serve", help="serve a node's public files over HTTP")
    s.add_argument("dir")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--verbose", action="store_true")

    c = sub.add_parser("config", help="node configuration controls").add_subparsers(dest="ccmd", required=True)
    x = c.add_parser("show")
    x.add_argument("dir")
    x = c.add_parser("set")
    x.add_argument("dir")
    x.add_argument("key")
    x.add_argument("value")
    x = c.add_parser("check")
    x.add_argument("dir")
    c.add_parser("explain")

    s = sub.add_parser("experiment", help="run the Seed-to-Network experiment (conditions A-H)")
    s.add_argument("--transport", default="file", choices=["file", "http"])
    s.add_argument("--out", help="directory for report.json and report.md")
    s.add_argument("--keep", action="store_true", help="keep the working directory")

    s = sub.add_parser("scale", help="measure discovery cost as the registry grows (FM-N15 probe)")
    s.add_argument("--sizes", default="10,40,160")
    s.add_argument("--out")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except (FileExistsError, FileNotFoundError, KeyError, ValueError, PermissionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(a) -> int:
    if a.cmd == "seed":
        c = create_seed(Path(a.dir), title=a.title, scope=a.scope, scope_terms=_terms(a.terms),
                        owner=a.owner, description=a.description, vocabulary=_vocab(a.synonym))
        print(f"seeded {c.corpus_id} at {a.dir}\n  fingerprint {c.manifest_sha256}")
        return 0
    if a.cmd == "validate":
        r = validate(Path(a.dir))
        print(r.summary())
        return 0 if r.ok else 1
    if a.cmd == "build":
        m = Corpus(Path(a.dir)).build()
        print(f"rebuilt; fingerprint {m['manifest_sha256']}")
        return 0
    if a.cmd == "spoke":
        print(add_spoke(Path(a.dir), a.name, title=a.title, scope=a.scope))
        return 0
    if a.cmd == "add":
        text = Path(a.text[1:]).read_text(encoding="utf-8") if a.text.startswith("@") else a.text
        p = add_page(Path(a.dir), a.spoke, title=a.title, text=text, scope=a.scope, when_to_use=a.when,
                     origin=a.origin, origin_depth=a.depth, derived_from=a.derived_from.split(),
                     ratified_by=a.ratified_by)
        print(f"{p.document_id}  {p.rel}  origin {p.origin} depth {p.origin_depth}")
        return 0
    if a.cmd == "supersede":
        p = supersede(Path(a.dir), a.document_id, text=a.text, reason=a.reason, origin=a.origin,
                      ratified_by=a.ratified_by)
        print(f"{p.document_id} v{p.version} supersedes {' '.join(p.supersedes)}")
        return 0
    if a.cmd == "copy":
        c = copy_corpus(Path(a.src), Path(a.dst), a.relation, title=a.title, scope=a.scope,
                        scope_terms=_terms(a.terms) if a.terms else None, vocabulary=_vocab(a.synonym),
                        spokes=_terms(a.spokes) if a.spokes else None)
        print(f"{a.relation}: {c.corpus_id} at {a.dst}\n  fingerprint {c.manifest_sha256}")
        return 0
    if a.cmd == "pack":
        print(pack(Path(a.src), Path(a.archive)))
        return 0
    if a.cmd == "unpack":
        print(unpack(Path(a.archive), Path(a.dst)))
        return 0
    if a.cmd == "node":
        return _node(a)
    if a.cmd == "hub":
        return _hub(a)
    if a.cmd == "route":
        print(route(Node(Path(a.dir)), a.query).explain())
        return 0
    if a.cmd == "ask":
        ans = ask(Node(Path(a.dir)), a.query)
        print(json.dumps(ans.envelope, indent=2) if a.json and ans.envelope else ans.render())
        return 0 if ans.kind in ("local", "remote") else 3
    if a.cmd == "cache-refresh":
        for ch in refresh_cache(Node(Path(a.dir))):
            print(f"{ch['document_id']}: cached v{ch['cached_version']}, current v{ch['current_version']} (kept)")
        return 0
    if a.cmd == "serve":
        from .server import make_server
        srv = make_server(Path(a.dir), a.host, a.port, a.verbose)
        print(f"serving node.json, node.html, corpora/ from {a.dir} at http://{a.host}:{srv.server_address[1]}/")
        print("  (local/, known/, cache/, config.json are never served)  Ctrl-C to stop")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    if a.cmd == "config":
        if a.ccmd == "explain":
            print(cfgmod.describe())
            return 0
        if a.ccmd == "show":
            print(json.dumps(cfgmod.load(Path(a.dir)), indent=2, sort_keys=True))
            return 0
        if a.ccmd == "set":
            print(json.dumps(cfgmod.set_value(Path(a.dir), a.key, a.value), indent=2, sort_keys=True))
            return 0
        if a.ccmd == "check":
            cfgmod.load(Path(a.dir))
            print("config OK")
            return 0
    if a.cmd == "experiment":
        from .experiment import run, to_markdown
        res = run(a.transport, keep=a.keep)
        md = to_markdown(res)
        if a.out:
            out = Path(a.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "report.json").write_text(json.dumps(res, indent=2, default=str))
            (out / "report.md").write_text(md)
        print(md)
        return 0
    if a.cmd == "scale":
        from .scale import probe, to_markdown as scale_md
        res = probe([int(x) for x in a.sizes.split(",")])
        md = scale_md(res)
        if a.out:
            out = Path(a.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "scale.json").write_text(json.dumps(res, indent=2))
            (out / "scale.md").write_text(md)
        print(md)
        return 0
    return 1


def _node(a) -> int:
    root = Path(a.dir)
    if a.ncmd == "init":
        n = Node.init(root, a.name)
        print(f"node {n.node_id} ({a.name}) at {root}")
        return 0
    n = Node(root)
    if a.ncmd == "seed":
        c = n.seed(title=a.title, scope=a.scope, scope_terms=_terms(a.terms), owner=a.owner,
                   vocabulary=_vocab(a.synonym))
        print(f"seeded {c.corpus_id} on {n.node_id}")
    elif a.ncmd == "carry":
        c = n.carry(Path(a.src), a.relation, title=a.title, scope=a.scope,
                    scope_terms=_terms(a.terms) if a.terms else None, vocabulary=_vocab(a.synonym),
                    spokes=_terms(a.spokes) if a.spokes else None)
        print(f"carrying {c.corpus_id} as {a.relation}")
    elif a.ncmd == "describe":
        d = n.describe(a.endpoint)
        print(f"{d['node_id']}: {len(d['corpora'])} corpora, endpoints {d['retrieval']['endpoints']}")
    elif a.ncmd == "learn":
        learned = n.learn(a.endpoint)
        print(f"learned {len(learned)}: {' '.join(learned)}")
    elif a.ncmd == "refresh":
        for nid, st in n.refresh().items():
            print(f"{nid}  {st}")
    elif a.ncmd == "known":
        for desc, meta in n.known():
            stale = " STALE" if n.is_stale(meta) else ""
            print(f"{desc['node_id']}  {desc.get('role')}  {desc.get('name')}  via={meta.get('via')}  "
                  f"verified={meta.get('verified')}{stale}")
            for e in desc.get("corpora", []):
                print(f"    {e['corpus_id']}  {e['title']}  [{e['relation']}, held as {e.get('held_as')}]")
    elif a.ncmd == "forget":
        n.forget(a.node_id)
    return 0


def _hub(a) -> int:
    if a.hcmd == "init":
        h = hubmod.init_hub(Path(a.dir), a.name, owner=a.owner)
        print(f"hub {h.node_id} at {a.dir}")
    elif a.hcmd == "register":
        print(hubmod.register(Node(Path(a.dir)), a.endpoint))
    elif a.hcmd == "refresh":
        for nid, st in hubmod.refresh(Node(Path(a.dir))).items():
            print(f"{nid}  {st}")
    elif a.hcmd == "rebuild":
        h, count = hubmod.rebuild(Path(a.dir), a.name, [Path(s) for s in a.sources])
        print(f"hub {h.node_id} rebuilt with {count} description(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
