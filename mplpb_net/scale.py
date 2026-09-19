"""
Scale probe -- FM-N15, "scale inversion", measured instead of assumed.

    python3 -m mplpb_net scale --sizes 10,40,160

Registers N synthetic nodes with one hub and measures what grows. The
reference hub rebuilds its whole manifest on every registration, so
registration cost is expected to grow roughly quadratically in N; a run
that shows this is a *finding*, reported as one. Learning and routing cost
should grow roughly linearly. None of this says anything about a
million-node network. It says where the reference implementation starts to
bend, which is the question F8 and F10 ask.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from . import hub as hubmod
from .node import Node
from .router import route
from .util import write_json


def _synthetic(root: Path, i: int) -> Node:
    """A node carrying one tiny corpus with a distinctive declared scope."""
    n = Node.init(root, f"n{i}")
    n.seed(title=f"Corpus {i}", scope=f"Topic{i} notes and topic{i} procedures",
           scope_terms=[f"topic{i}", f"subject{i}"], owner="probe")
    return n


def probe(sizes: list[int]) -> dict:
    rows = []
    for n_nodes in sizes:
        tmp = Path(tempfile.mkdtemp(prefix="mplpb-scale-"))
        try:
            t = time.time()
            nodes = [_synthetic(tmp / f"n{i}", i) for i in range(n_nodes)]
            t_nodes = time.time() - t
            h = hubmod.init_hub(tmp / "hub", "hub")
            t = time.time()
            for n in nodes:
                hubmod.register(h, n.root.as_uri())
            t_register = time.time() - t
            registry = next(c for c in h.corpora()).root / "nodes" / "registry.json"
            asker = Node.init(tmp / "asker", "asker")
            t = time.time()
            asker.learn(h.root.as_uri())
            t_learn = time.time() - t
            t = time.time()
            queries = [f"topic{i} procedures" for i in range(0, n_nodes, max(1, n_nodes // 10))]
            correct = 0
            for q in queries:
                r = route(asker, q)
                correct += r.kind == "remote"
            t_route = (time.time() - t) / len(queries)
            rows.append({
                "nodes": n_nodes,
                "create_nodes_s": round(t_nodes, 3),
                "register_all_s": round(t_register, 3),
                "register_per_node_ms": round(1000 * t_register / n_nodes, 1),
                "registry_bytes": registry.stat().st_size,
                "hub_files": sum(1 for p in (tmp / "hub").rglob("*") if p.is_file()),
                "learn_s": round(t_learn, 3),
                "route_ms": round(1000 * t_route, 2),
                "routing_correct": f"{correct}/{len(queries)}",
            })
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return {"rows": rows}


def to_markdown(res: dict) -> str:
    rows = res["rows"]
    keys = list(rows[0].keys())
    out = ["# Scale probe (FM-N15)", "", "| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    for r in rows:
        out.append("| " + " | ".join(str(r[k]) for k in keys) + " |")
    if len(rows) > 1:
        a, b = rows[0], rows[-1]
        f = b["nodes"] / a["nodes"]
        out += ["", f"Nodes grew {f:.0f}x. Per-node registration cost grew "
                f"{b['register_per_node_ms'] / max(a['register_per_node_ms'], 0.001):.1f}x; "
                f"routing cost grew {b['route_ms'] / max(a['route_ms'], 0.001):.1f}x; "
                f"registry size grew {b['registry_bytes'] / a['registry_bytes']:.1f}x."]
    return "\n".join(out) + "\n"
