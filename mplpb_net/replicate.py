"""
Replication -- copying a corpus, and saying what the copy is.

Replication is not synchronization (§4). After a copy, the two directories
may diverge, and the relation between them has to be declared rather than
inferred from how similar their text looks:

    mirror       byte-identical; same corpus ID; same fingerprint
    descendant   new corpus ID; seeded from the source; owns a new domain
    fork         new corpus ID; seeded from the source; continues its domain
                 under separate governance
    partial      new corpus ID; seeded from the source; only some spokes

A mirror is not a new corpus, so nothing inside it changes; *which machines
hold a mirror* is recorded by those machines, not inside the corpus. Every
other relation mints a new corpus ID, records `seeded_from` (source ID and
fingerprint), and appends a hash-chained lineage event. Seeded-from is
lineage, not endorsement.

Transport is separate from replication (§12). `pack` and `unpack` move a
corpus or a whole node as a ZIP archive; nothing about the corpus depends on
how it travelled.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

from .corpus import CORPUS_JSON, VOCAB_JSON, Corpus, new_corpus_id
from .page import ROOT_PAGE, bump_updated
from .util import now_iso, read_json, write_json
from .validate import validate

COPY_RELATIONS = ("mirror", "descendant", "fork", "partial")
STRUCTURAL = {"spec", "_net", "_log"}


class ReplicationError(Exception):
    pass


def verify_source(src: Path) -> Corpus:
    src = Path(src)
    report = validate(src, only={"N.1", "N.2", "N.3"})
    if not report.ok:
        raise ReplicationError(
            "refusing to replicate a corpus that does not verify:\n" + report.summary()
        )
    return Corpus(src)


def copy_corpus(
    src: Path,
    dst: Path,
    relation: str = "mirror",
    *,
    title: str | None = None,
    scope: str | None = None,
    scope_terms: list[str] | None = None,
    vocabulary: dict | None = None,
    spokes: list[str] | None = None,
    note: str = "",
) -> Corpus:
    if relation not in COPY_RELATIONS:
        raise ValueError(f"relation must be one of {COPY_RELATIONS}")
    source = verify_source(src)
    dst = Path(dst)
    if dst.exists():
        raise FileExistsError(f"{dst} already exists")
    src_ident = source.identity
    src_fp = source.manifest_sha256
    shutil.copytree(source.root, dst)
    copy = Corpus(dst)

    if relation == "mirror":
        if copy.compute_manifest()["manifest_sha256"] != src_fp:
            shutil.rmtree(dst, ignore_errors=True)
            raise ReplicationError("mirror does not reproduce the source fingerprint")
        return copy

    if relation == "partial":
        if not spokes:
            raise ValueError("a partial copy must name the spokes it keeps")
        _prune(dst, set(spokes))

    ident = dict(src_ident)
    ident.update(
        {
            "corpus_id": new_corpus_id(),
            "relation": relation,
            "seeded_from": {
                "corpus_id": src_ident["corpus_id"],
                "manifest_sha256": src_fp,
                "title": src_ident.get("title", ""),
            },
            "created": now_iso(),
        }
    )
    if title:
        ident["title"] = title
    if scope:
        ident["scope"] = scope
    if scope_terms:
        ident["scope_terms"] = [t.lower() for t in scope_terms]
    write_json(dst / CORPUS_JSON, ident)

    vocab = read_json(dst / VOCAB_JSON)
    for t in ident["scope_terms"]:
        vocab.setdefault(t, [])
    for t, syns in (vocabulary or {}).items():
        vocab[t.lower()] = sorted(set(vocab.get(t.lower(), [])) | {s.lower() for s in syns})
    write_json(dst / VOCAB_JSON, vocab)

    copy.append_lineage(
        relation,
        corpus_id=ident["corpus_id"],
        from_corpus=src_ident["corpus_id"],
        from_manifest=src_fp,
        note=note,
    )
    copy.log(
        f"{ident['corpus_id']} created as {relation} of {src_ident['corpus_id']} "
        f"(fingerprint {src_fp[:16]}…). Lineage, not endorsement."
    )
    copy.build()
    report = validate(dst)
    if not report.ok:
        raise ReplicationError("copy does not validate:\n" + report.summary())
    return copy


def _prune(root: Path, keep: set[str]) -> None:
    removed = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name not in STRUCTURAL and child.name not in keep:
            if (child / "_index.html").exists():
                shutil.rmtree(child)
                removed.append(child.name)
    index = root / ROOT_PAGE
    text = index.read_text(encoding="utf-8")
    for name in removed:
        text = re.sub(
            rf'  <li><a href="{re.escape(name)}/_index.html">.*?</li>\n', "", text, flags=re.S
        )
    index.write_text(text, encoding="utf-8")
    bump_updated(index)


def pack(src: Path, archive: Path) -> Path:
    """Write a directory (a corpus or a whole node) into a ZIP archive.
    Keys are never packed: a node's secret stays on its machine."""
    src, archive = Path(src).resolve(), Path(archive)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            rel = path.relative_to(src).as_posix()
            if path.is_file() and not rel.startswith("local/") and path.suffix != ".key":
                zf.write(path, rel)
    return archive


def unpack(archive: Path, dst: Path) -> Path:
    dst = Path(dst)
    if dst.exists() and any(dst.iterdir()):
        raise FileExistsError(f"{dst} exists and is not empty")
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            target = (dst / name).resolve()
            if not str(target).startswith(str(dst.resolve())):
                raise ReplicationError(f"archive entry escapes destination: {name}")
        zf.extractall(dst)
    return dst
