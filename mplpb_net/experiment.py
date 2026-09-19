"""
The Seed-to-Network experiment (§21), runnable end to end.

    python3 -m mplpb_net experiment [--transport file|http] [--out DIR] [--keep]

Conditions A-H run in a temporary directory on this machine. With
`--transport http` every node is served over real HTTP on localhost, the hub
is removed by stopping its server, and origin loss stops and deletes node A.
With `--transport file` the same steps use filesystem endpoints.

What this run is, honestly: a *mechanical* rehearsal of the protocol with
corpora and queries written by the same author as the code. It shows the
machinery behaves as specified. It does not show that strangers can recover
a corpus (that needs the blind protocol in Docs/PROTOCOL.md), that declared
scope beats flat retrieval on real questions (that needs the ablation), or
anything about scale (FM-N15). The report says so on its face.
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from . import config as cfgmod
from . import hub as hubmod
from .corpus import Corpus, add_page, add_spoke, supersede
from .node import Node
from .replicate import copy_corpus, pack, unpack
from .retrieve import ask, refresh_cache, verify_envelope
from .server import serve_in_thread
from .util import read_json
from .validate import CHECKS, validate

DOMAINS = {
    "B": dict(
        title="Kiln Notes", scope="Kiln firing schedules, glaze chemistry, and ceramic defects",
        terms=["kiln", "glaze", "firing", "ceramic"],
        vocab={"kiln": ["furnace"], "ceramic": ["pottery", "clay", "stoneware"]},
        spoke=("kiln", "Kiln", "Firing schedules and glaze behaviour"),
        pages=[
            ("Bisque firing", "Bisque firing schedule for greenware",
             "Fire greenware slowly to about 1000 C. Climb no faster than 100 C per hour through "
             "the first 600 C so water and organics leave before the clay body tightens."),
            ("Glaze crawling", "Why glaze pulls back from the clay body",
             "Crawling happens when glaze shrinks away from dusty or oily bisque, or when it is "
             "applied too thickly. Wipe bisque with a damp sponge and apply thinner coats."),
        ],
    ),
    "C": dict(
        title="Apiary Notes", scope="Beekeeping practice: hive inspection, honey harvest, colony health",
        terms=["beekeeping", "hive", "honey", "colony"],
        vocab={"beekeeping": ["bees", "bee", "apiary"], "colony": ["swarm"]},
        spoke=("hive", "Hive", "Inspection and harvest"),
        pages=[
            ("Hive inspection", "What to check on a routine hive inspection",
             "Inspect every seven to ten days in season. Look for eggs, capped brood, stores, and "
             "queen cells. Work calmly and replace frames in their original order."),
            ("Honey harvest", "When and how to take honey",
             "Take only capped honey frames and leave enough stores for winter. Uncap, extract, "
             "strain, and let the honey settle before bottling."),
        ],
    ),
    "D": dict(
        title="Bicycle Workshop", scope="Bicycle maintenance: chains, brakes, derailleurs, wheels",
        terms=["bicycle", "chain", "brake", "derailleur"],
        vocab={"bicycle": ["bike", "cycle", "cycling"], "brake": ["braking"]},
        spoke=("repair", "Repair", "Maintenance procedures"),
        pages=[
            ("Brake squeal", "Why rim or disc brakes squeal and how to stop it",
             "Squeal usually means contamination or poor alignment. Clean the rotor or rim with "
             "alcohol, check pad wear, and toe in rim brake pads slightly."),
            ("Chain wear", "Measuring chain stretch and when to replace",
             "Measure with a chain checker. Replace at 0.5 percent wear on 11 and 12 speed "
             "drivetrains, 0.75 percent on older ones, before the cassette wears too."),
        ],
    ),
}

FORK = dict(
    title="Rooftop Apiary", scope="Urban beekeeping on rooftops: hive placement, honey, colony wind exposure",
    terms=["beekeeping", "hive", "honey", "rooftop"],
    vocab={"beekeeping": ["bees", "bee", "apiary"], "rooftop": ["roof"]},
    spoke=("rooftop", "Rooftop", "Rooftop placement"),
    pages=[
        ("Rooftop hive placement", "Placing a hive on a roof",
         "Rooftop hives need a windbreak, a water source within a short flight, and a floor "
         "rated for the loaded weight of a full hive."),
    ],
)

#: (query, expected class, expected owner label or None)
QUERIES = [
    ("how do I validate a copy of the seed corpus?", "local", "SEED"),
    ("what does the provenance envelope contain on the network?", "local", "SEED"),
    ("bisque firing schedule for a kiln", "remote", "B"),
    ("why is my glaze crawling on the ceramic?", "remote", "B"),
    ("my bike brakes squeal", "remote", "D"),
    ("when should I replace a bicycle chain?", "remote", "D"),
    ("pottery furnace temperature", "remote", "B"),
    ("hive inspection checklist for honey bees", "ambiguous", None),
    ("when to harvest honey from the hive", "ambiguous", None),
    ("rooftop hive placement and wind", "remote", "FORK"),
    ("sourdough starter hydration", "not_found", None),
    ("tax rules for selling a house", "not_found", None),
]


class Clock:
    def __init__(self):
        self.actions = []

    def act(self, label: str):
        self.actions.append(label)


def _stdlib_only() -> tuple[bool, list]:
    pkg = Path(__file__).resolve().parent
    names = set()
    for py in pkg.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    outside = sorted(n for n in names if n != "mplpb_net" and not _is_stdlib(n))
    return not outside, outside


def _is_stdlib(name: str) -> bool:
    if name == "__future__":
        return True
    if hasattr(sys, "stdlib_module_names"):  # Python 3.10+
        return name in sys.stdlib_module_names
    import importlib.util
    import sysconfig

    spec = importlib.util.find_spec(name)
    if spec is None:
        return False
    if spec.origin in ("built-in", "frozen", None):
        return True
    return spec.origin.startswith(sysconfig.get_paths()["stdlib"]) and "site-packages" not in spec.origin


def _dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def _grow(corpus_root: Path, spec: dict, clock: Clock) -> None:
    name, title, scope = spec["spoke"]
    add_spoke(corpus_root, name, title=title, scope=scope, build=False)
    for ptitle, pscope, text in spec["pages"]:
        add_page(corpus_root, name, title=ptitle, text=text, scope=pscope, build=False)
    Corpus(corpus_root).build()
    clock.act(f"grow {spec['title']}")


def run(transport: str = "file", workdir: Path | None = None, keep: bool = False) -> dict:
    t0, c0 = time.time(), time.process_time()
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="mplpb-net-exp-"))
    tmp.mkdir(parents=True, exist_ok=True)
    clock = Clock()
    servers = {}
    results: dict = {"transport": transport, "conditions": {}, "metrics": {}, "queries": []}

    def endpoint(node: Node) -> str:
        if transport == "http":
            srv, url = serve_in_thread(node.root)
            servers[node.node_id] = srv
            return url
        return node.root.as_uri()

    def stop(node_id: str):
        srv = servers.pop(node_id, None)
        if srv:
            srv.shutdown()
            srv.server_close()

    try:
        # -- A: seed -------------------------------------------------------------
        A = Node.init(tmp / "A", "node-a")
        seed = A.seed(
            title="Networked MPLPB Seed",
            scope="The Networked MPLPB corpus format: seeds, validation, replication, network routing, provenance",
            scope_terms=["mplpb", "seed", "corpus", "validation", "provenance", "replication", "network"],
            owner="Mitchell D. McPhetridge",
            vocabulary={"validation": ["validate", "check"], "replication": ["copy", "mirror"],
                        "provenance": ["envelope", "citation"]},
        )
        add_spoke(seed.root, "notes", title="Field Notes", scope="Notes on running the seed", build=False)
        add_page(seed.root, "notes", title="First copy", text="The first copy took one command.",
                 scope="Notes on the first copy", build=False)
        supersede(seed.root, "NOTES-001", text="The first copy took one command and one validation run.",
                  reason="added the validation step")
        A.describe()
        seed_fp = seed.manifest_sha256
        seed_id = seed.corpus_id
        seed_ok = validate(seed.root).ok
        clock.act("seed")
        results["conditions"]["A_seed"] = {"corpus_id": seed_id, "fingerprint": seed_fp, "valid": seed_ok}

        # -- B: replication ------------------------------------------------------
        nodes = {"A": A}
        mirrors_ok = []
        for label in ("B", "C", "D"):
            n = Node.init(tmp / label, f"node-{label.lower()}")
            m = n.carry(seed.root, "mirror")
            mirrors_ok.append(validate(m.root).ok and m.manifest_sha256 == seed_fp)
            nodes[label] = n
            clock.act(f"mirror to {label}")
        results["conditions"]["B_replication"] = {"mirrors_valid": mirrors_ok}

        # -- C: differentiation --------------------------------------------------
        owners = {"SEED": seed_id}
        desc_valid = []
        for label, spec in DOMAINS.items():
            n = nodes[label]
            c = n.carry(n.corpus(seed_id).root, "descendant", title=spec["title"], scope=spec["scope"],
                        scope_terms=spec["terms"], vocabulary=spec["vocab"])
            _grow(c.root, spec, clock)
            desc_valid.append(validate(c.root).ok)
            owners[label] = c.corpus_id
        # A fork of C's corpus lives on D: a true scope collision with C.
        fork = nodes["D"].carry(nodes["C"].corpus(owners["C"]).root, "fork", title=FORK["title"],
                                scope=FORK["scope"], scope_terms=FORK["terms"], vocabulary=FORK["vocab"])
        _grow(fork.root, FORK, clock)
        # A machine-derived page two steps from a human source (laundering probe).
        add_page(fork.root, "rooftop", title="Rooftop hive summary", origin="machine",
                 derived_from=[f"{owners['C']}:HIVE-001"],
                 text="Machine summary: rooftop hive placement needs wind shelter and water; inspect often.",
                 scope="Machine-written summary of rooftop hive placement")
        desc_valid.append(validate(fork.root).ok)
        owners["FORK"] = fork.corpus_id
        for n in nodes.values():
            n.describe()
        results["conditions"]["C_differentiation"] = {"descendants_valid": desc_valid,
                                                       "corpora": owners}

        # -- D: discovery ----------------------------------------------------------
        eps = {label: endpoint(n) for label, n in nodes.items()}
        for label, n in nodes.items():
            n.describe([eps[label]])
        H = hubmod.init_hub(tmp / "H", "hub-1")
        hub_id = H.node_id
        eps["H"] = endpoint(H)
        H.describe([eps["H"]])
        for label in nodes:
            hubmod.register(H, eps[label])
            clock.act(f"register {label}")
        for label, n in nodes.items():
            n.learn(eps["H"])
            clock.act(f"{label} learns hub")
        results["conditions"]["D_discovery"] = {
            "hub": H.node_id, "known_per_node": {l: len(n.known()) for l, n in nodes.items()}}

        # -- E: cross-node retrieval (asked from A) --------------------------------
        def run_queries(asker: Node, tag: str, only=None):
            rows = []
            for q, expect, owner in QUERIES:
                if only and expect not in only:
                    continue
                ans = ask(asker, q)
                got_owner = ans.envelope["corpus_id"] if ans.envelope else None
                ok_route = ans.kind == expect and (owner is None or got_owner == owners[owner])
                prov = None
                if ans.kind == "remote" and ans.envelope:
                    env = ans.envelope
                    cache = asker.root / "cache" / env["corpus_id"] / env["path"]
                    arts = asker.root / "cache" / "_artifacts"
                    manifest = read_json(arts / f"manifest-{env['manifest_sha256'][:24]}.json")
                    desc = read_json(arts / f"description-{env['served_by']['description_sha256'][:24]}.json")
                    vok, _ = verify_envelope(env, cache.read_bytes(), manifest, desc)
                    server_hop = env["route"][-1]
                    prov = bool(vok and env["corpus_id"] == owners[owner]
                                and server_hop["role"] == "server"
                                and server_hop["node_id"] == env["served_by"]["node_id"]
                                and env["served_by"]["node_id"] != hub_id)
                rows.append({"phase": tag, "query": q, "expected": expect, "got": ans.kind,
                             "owner_ok": ok_route, "provenance_ok": prov,
                             "served_depth": ans.envelope["origin_depth"] if ans.envelope else None,
                             "withheld": ans.withheld})
            return rows

        rows_e = run_queries(A, "E")
        results["queries"] += rows_e
        routable = [r for r in rows_e if r["expected"] in ("local", "remote")]
        colls = [r for r in rows_e if r["expected"] == "ambiguous"]
        absent = [r for r in rows_e if r["expected"] == "not_found"]
        remotes = [r for r in rows_e if r["got"] == "remote"]
        m = results["metrics"]
        m["routing_accuracy"] = sum(r["owner_ok"] for r in routable) / len(routable)
        m["ambiguity_preservation"] = sum(r["got"] == "ambiguous" for r in colls) / len(colls)
        m["absent_reported"] = sum(r["got"] == "not_found" for r in absent) / len(absent)
        m["provenance_retention"] = (sum(bool(r["provenance_ok"]) for r in remotes) / len(remotes)) if remotes else 0.0
        m["depth_policy_respected"] = all((r["served_depth"] or 0) <= A.cfg["d_max"] for r in rows_e)
        m["laundering_probe_withheld"] = any(r["withheld"] for r in rows_e if "rooftop" in r["query"])

        # Supersession propagation: B revises a page A has cached.
        supersede(nodes["B"].corpus(owners["B"]).root, "KILN-001",
                  text="Fire greenware slowly to about 1000 C; hold 10 minutes at peak.",
                  reason="added hold time")
        nodes["B"].describe()
        changes = refresh_cache(A)
        m["supersession_propagated"] = any(c["document_id"] == "KILN-001" for c in changes)
        cached_kept = (A.root / "cache" / owners["B"] / "kiln" / "bisque_firing.html").exists()
        m["history_kept_in_cache"] = cached_kept
        clock.act("supersede + refresh")

        # -- Offline retention ----------------------------------------------------
        def local_capabilities(n: Node, label: str) -> list[bool]:
            caps = []
            caps.append(all(validate(c.root).ok for c in n.corpora()))
            caps.append(ask(n, "how do I validate a copy of the seed corpus?").kind == "local")
            dst = tmp / f"offline-copy-{label}"
            try:
                copy_corpus(n.corpus(seed_id).root, dst, "mirror")
                caps.append(validate(dst).ok)
            except Exception:
                caps.append(False)
            try:
                d2 = tmp / f"offline-desc-{label}"
                cc = copy_corpus(n.corpus(seed_id).root, d2, "descendant", title="Offline spoke test")
                add_spoke(cc.root, "offline", title="Offline", scope="A spoke added while disconnected")
                caps.append(validate(cc.root).ok)
            except Exception:
                caps.append(False)
            try:
                caps.append(pack(n.corpus(seed_id).root, tmp / f"offline-{label}.zip").exists())
            except Exception:
                caps.append(False)
            return caps

        before = local_capabilities(nodes["B"], "B-on")
        cfgmod.set_value(nodes["B"].root, "offline", "true")
        cfgmod.set_value(nodes["B"].root, "allow_connectors", "zip")  # no reachable peers at all
        after = local_capabilities(nodes["B"], "B-off")
        remote_while_off = ask(nodes["B"], "my bike brakes squeal").kind
        m["offline_retention"] = sum(after) / max(1, sum(before))
        m["offline_remote_reported_unavailable"] = remote_while_off == "unavailable"
        (nodes["B"].root / "config.json").write_text(json.dumps({"node_name": "node-b"}))

        # -- F: hub loss --------------------------------------------------------
        stop(hub_id)
        shutil.rmtree(H.root)
        clock.act("remove hub")
        rows_f = run_queries(A, "F", only={"local", "remote"})
        results["queries"] += rows_f
        m["after_hub_loss_answered"] = sum(r["owner_ok"] for r in rows_f) / len(rows_f)

        # -- G: origin loss -------------------------------------------------------
        stop(A.node_id)
        shutil.rmtree(A.root)
        clock.act("remove origin A")
        survivors = [nodes[l].corpus(seed_id) for l in ("B", "C", "D")]
        m["origin_independence"] = sum(
            1 for c in survivors if validate(c.root).ok and c.manifest_sha256 == seed_fp
        ) / len(survivors)

        # -- H: new generation, seeded by hand from C without A --------------------
        zip_path = pack(nodes["C"].corpus(seed_id).root, tmp / "sneakernet" / "seed-from-C.zip")
        carried = unpack(zip_path, tmp / "E-incoming")
        clock.act("sneakernet C -> E")
        E = Node.init(tmp / "E", "node-e")
        e_seed = E.carry(carried, "mirror")
        E.describe([endpoint(E)])
        H2, count = hubmod.rebuild(tmp / "H2", "hub-2", [nodes[l].root for l in ("B", "C", "D")])
        eps["H2"] = endpoint(H2)
        H2.describe([eps["H2"]])
        E.learn(eps["H2"])
        clock.act("rebuild hub from survivors; E joins")

        props = {}
        props["corpus_id_preserved"] = e_seed.corpus_id == seed_id
        props["fingerprint_preserved"] = e_seed.manifest_sha256 == seed_fp
        props["scope_readable"] = bool(e_seed.identity["scope"])
        props["boot_block_present"] = "Boot block" in (e_seed.root / "index.html").read_text()
        vtext = (e_seed.root / "spec" / "validation.html").read_text()
        props["validation_rules_in_prose"] = all(cid in vtext for cid in CHECKS)
        pages = e_seed.pages()
        cur = next(p for p in pages.values() if p.document_id == "NOTES-001" and p.status == "current")
        props["current_vs_retired"] = any(p.status == "retired" for p in pages.values())
        props["supersession_traceable"] = bool(cur.supersedes) and any(
            p.document_id == cur.supersedes[0] and p.status == "retired" for p in pages.values())
        props["lineage_chain_verifies"] = validate(e_seed.root, only={"N.3"}).ok
        props["instantiation_guide_present"] = (e_seed.root / "spec" / "seed.html").exists()
        try:
            gen = copy_corpus(e_seed.root, tmp / "E-descendant", "descendant", title="Generation 2")
            props["can_seed_next_generation"] = validate(gen.root).ok
        except Exception:
            props["can_seed_next_generation"] = False
        m["recovery_rate"] = sum(props.values()) / len(props)
        results["conditions"]["H_new_generation"] = {"recovered_properties": props,
                                                     "hub_rebuilt_from_descriptions": count}
        rows_h = []
        for q, expect, owner in QUERIES:
            if expect != "remote":
                continue
            ans = ask(E, q)
            rows_h.append({"phase": "H", "query": q, "expected": expect, "got": ans.kind,
                           "owner_ok": ans.kind == "remote" and ans.envelope["corpus_id"] == owners[owner],
                           "provenance_ok": ans.envelope["verified"] if ans.envelope else None,
                           "served_depth": ans.envelope["origin_depth"] if ans.envelope else None,
                           "withheld": ans.withheld})
        results["queries"] += rows_h
        m["new_generation_routing"] = sum(r["owner_ok"] for r in rows_h) / len(rows_h)

        # -- replication integrity across everything copied ------------------------
        copies = mirrors_ok + desc_valid + [props["fingerprint_preserved"], props["can_seed_next_generation"]]
        m["replication_integrity"] = sum(copies) / len(copies)

        stdlib, outside = _stdlib_only()
        results["burden"] = {
            "stdlib_only": stdlib,
            "non_stdlib_imports": outside,
            "persistent_services": 0 if transport == "file" else "one static file server per node (optional)",
            "administrative_actions": len(clock.actions),
            "wall_seconds": round(time.time() - t0, 2),
            "cpu_seconds": round(time.process_time() - c0, 2),
            "storage_bytes": {p.name: _dir_bytes(p) for p in sorted(tmp.iterdir()) if p.is_dir()},
        }
        try:
            import resource
            results["burden"]["peak_rss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except ImportError:  # pragma: no cover - Windows
            pass
        results["caveat"] = (
            "Mechanical rehearsal. Corpora, queries, and code share one author; nodes share one "
            "machine. This does not test stranger recovery, retrieval quality against a flat "
            "baseline, adversarial peers, or scale."
        )
        results["workdir"] = str(tmp) if keep else None
        return results
    finally:
        for nid in list(servers):
            stop(nid)
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def to_markdown(results: dict) -> str:
    m = results["metrics"]
    lines = [
        f"# Seed-to-Network run ({results['transport']} transport)", "",
        f"> {results['caveat']}", "",
        "| Metric | Value |", "|---|---|",
    ]
    for k, v in m.items():
        lines.append(f"| {k} | {v if isinstance(v, bool) else f'{v:.3f}'} |")
    lines += ["", "## Queries", "", "| Phase | Query | Expected | Got | Owner ok | Provenance ok |",
              "|---|---|---|---|---|---|"]
    for r in results["queries"]:
        lines.append(f"| {r['phase']} | {r['query']} | {r['expected']} | {r['got']} | "
                     f"{r['owner_ok']} | {'' if r['provenance_ok'] is None else r['provenance_ok']} |")
    b = results["burden"]
    lines += ["", "## Infrastructure burden", ""]
    for k, v in b.items():
        lines.append(f"- **{k}**: {v}")
    lines += ["", "## New-generation recovery (Condition H)", ""]
    for k, v in results["conditions"]["H_new_generation"]["recovered_properties"].items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines) + "\n"
