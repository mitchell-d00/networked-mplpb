"""
Node configuration -- `config.json` in the node directory.

Toggle policy (inherited from Smart Local): every key here changes
observable behaviour, and a test exercises each one. A key that did nothing
would be a claim the code does not keep, so there are none.

Configuration is local policy. It travels with the machine, never with a
corpus: two nodes carrying the same corpus may serve it under different
rules, and that is the point (§15: "the metadata travels; the policy remains
local").
"""

from __future__ import annotations

from pathlib import Path

from .util import read_json, write_json

#: key -> (default, type, description)
SCHEMA = {
    "d_max": (1, int,
              "Serve pages whose origin depth is at most this. 0 serves only human-authored "
              "or ratified pages."),
    "ownership_margin": (1.5, float,
                         "A corpus owns a query only if its scope score leads the runner-up by "
                         "this factor; otherwise the result is AMBIGUOUS."),
    "min_scope_score": (2.0, float,
                        "Below this scope score a corpus is not considered to own anything."),
    "precedence": ([], list,
                   "Corpus IDs that win an ambiguity among themselves and others. Local policy, "
                   "reported in the routing note whenever it is used."),
    "offline": (False, bool,
                "Refuse every network connector. File and archive connectors still work: "
                "sneakernet is not a network dependency."),
    "allow_connectors": (["file", "zip", "http"], list,
                         "Which connector schemes may be used at all."),
    "timeout_seconds": (5.0, float, "HTTP connector timeout."),
    "verify": ("require", str,
               "require: reject unsigned or badly signed descriptions and unverifiable pages. "
               "warn: accept but mark unverified. off: skip checks (testing only)."),
    "stale_after_days": (30.0, float,
                         "A description not refreshed for this long is reported as stale in "
                         "routing, and tried after fresh holders."),
    "max_hops": (2, int, "How many hub-to-hub steps discovery will follow."),
    "cache_remote": (True, bool,
                     "Keep retrieved remote pages with their envelopes in cache/. Cached "
                     "copies are never served as if local."),
    "include_retired": (False, bool,
                        "Allow retired pages to be returned by retrieval (clearly marked)."),
}

VERIFY_MODES = ("require", "warn", "off")


def defaults() -> dict:
    return {k: (list(v[0]) if isinstance(v[0], list) else v[0]) for k, v in SCHEMA.items()}


def check(cfg: dict) -> list[str]:
    problems = []
    for key, value in cfg.items():
        if key == "node_name":
            continue
        if key not in SCHEMA:
            problems.append(f"unknown key {key!r}")
            continue
        typ = SCHEMA[key][1]
        if typ is float and isinstance(value, int) and not isinstance(value, bool):
            continue
        if not isinstance(value, typ) or (typ is int and isinstance(value, bool)):
            problems.append(f"{key} must be {typ.__name__}, got {type(value).__name__}")
    if cfg.get("verify") not in VERIFY_MODES:
        problems.append(f"verify must be one of {VERIFY_MODES}")
    if cfg.get("d_max", 0) < 0:
        problems.append("d_max must be >= 0")
    if cfg.get("ownership_margin", 1) < 1:
        problems.append("ownership_margin must be >= 1")
    return problems


def load(node_root: Path) -> dict:
    cfg = defaults()
    path = Path(node_root) / "config.json"
    if path.exists():
        cfg.update(read_json(path))
    problems = check(cfg)
    if problems:
        raise ValueError(f"{path}: " + "; ".join(problems))
    return cfg


def parse_value(key: str, raw: str):
    if key not in SCHEMA:
        raise KeyError(f"unknown key {key!r}; known: {', '.join(SCHEMA)}")
    typ = SCHEMA[key][1]
    if typ is bool:
        if raw.lower() in ("1", "true", "yes", "on"):
            return True
        if raw.lower() in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{key} expects true/false")
    if typ is list:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return typ(raw)


def set_value(node_root: Path, key: str, raw: str) -> dict:
    path = Path(node_root) / "config.json"
    stored = read_json(path) if path.exists() else {}
    stored[key] = parse_value(key, raw)
    merged = defaults()
    merged.update(stored)
    problems = check(merged)
    if problems:
        raise ValueError("; ".join(problems))
    write_json(path, stored)
    return merged


def describe() -> str:
    lines = []
    for key, (default, typ, text) in SCHEMA.items():
        lines.append(f"{key}  ({typ.__name__}, default {default!r})\n    {text}")
    return "\n".join(lines)
