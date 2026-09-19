# Networked MPLPB

Grow a knowledge network from a seed. Standard library only — no `pip
install`, no database, no required server, no model.

An [MPLPB local web](#background) is a bounded knowledge corpus that is an
actual website: plain HTML files in a directory, connected by relative links,
starting at `index.html`. This package is what happens when there are many of
them, on many machines, kept by people who do not coordinate. A corpus that can
be copied and still interpreted is a **seed**. A machine that carries seeds and
says so in a signed description is a **node**. A list of node descriptions,
kept as an ordinary corpus, is a **hub**. Nothing in that stack has to stay
running for the rest to stay meaningful.

```
$ mplpb-net ask node-a "bisque firing schedule for a kiln"

Bisque firing

  Bisque firing Fire greenware slowly to about 1000 C. Climb no faster than
  100 C per hour through the first 600 C ...

  [C-9BDBB6132CCA:KILN-001 · kiln/bisque_firing.html · v1 · current · origin human d0]
  served by N-21284C75FCE1DE36  verified=True
  route: N-DAF79EA363CDB2D3(requester) -> N-7FC669B5D1DA93FA(discovery) -> N-21284C75FCE1DE36(server)
  note: C-9BDBB6132CCA owns this by declared scope
```

The answer came from another machine. The citation names the corpus that owns
it, the node that served it, and the hub that only said where to look — and
every one of those claims can be checked by someone who was not there.

## What makes it networked

Five rules, each a code path rather than a paragraph of advice.

**It routes by declared scope, and reports ambiguity instead of merging it.**
Every corpus declares a scope and a list of scope terms from a vocabulary it
carries. When one corpus owns a question, that is where the answer comes from.
When two plausibly do — a corpus and its fork, say — the result is
`ambiguous`, with both corpora and their lineage, and no page. `mplpb-net
route` shows which query term matched which declaration.

**Provenance can be checked, not just carried.** Retrieval is static: fetch
the serving node's signed description, the corpus manifest, the catalog, the
page, and check each against the one before. Every page reduces to an Ed25519
signature by the node that served it over a fingerprint that names the page's
hash. Hubs appear in the route as `discovery`, caches as signed `relayed, did
not author` attestations. Neither can become the source.

**Unavailable is never impersonated.** If the owner is known and unreachable,
the answer is *Relevant corpus known; node unavailable.* A byte-identical
mirror of the same corpus may serve instead, and the citation says so. Another
corpus answering in the owner's place is not an option the code has.

**Machine-written pages carry their distance from a human.** `origin` is
human, machine, or ratified; `origin-depth` is one more than the deepest
source; copying machine text does not reset it; ratification does, and must
record who and when. Each node sets `d_max`, and pages beyond it are withheld
and counted.

**The rules travel with the copy.** Every seed carries `spec/validation.html`,
all sixteen checks in plain language, generated from the same table the code
enforces. A test fails if they drift. A stranger with a browser and
`sha256sum` can verify a copy without this repository.

## Install

```bash
git clone https://github.com/<you>/networked-mplpb.git
cd networked-mplpb
python3 -m mplpb_net validate Seed        # works immediately, no install step
```

Or install it so `mplpb-net` is on your path:

```bash
pip install -e .
mplpb-net validate Seed
```

Python 3.9 or newer. Nothing outside the standard library — including the
signature scheme, which is RFC 8032 Ed25519 in pure Python (see *What this
does not claim*). The experiment checks this by parsing every import.

## A network in twelve commands

```bash
mplpb-net node init A --name alpha
mplpb-net node carry A Seed --relation mirror                 # A carries the reference seed

mplpb-net node init B --name beta
mplpb-net node carry B Seed --relation descendant \
    --title "Kiln Notes" --scope "Kiln firing and glazes" \
    --terms kiln,glaze,firing --synonym kiln:furnace
mplpb-net spoke B/corpora/C-XXXX kiln --title Kiln --scope "Firing schedules"
mplpb-net add   B/corpora/C-XXXX kiln --title "Bisque firing" \
    --scope "Bisque schedule" --text "Fire slowly to 1000 C."
mplpb-net node describe B

mplpb-net hub init H --name hub-1
mplpb-net hub register H file://$PWD/B
mplpb-net hub register H file://$PWD/A
mplpb-net node learn A file://$PWD/H

mplpb-net ask A "bisque firing schedule for a kiln"
```

Replace `file://` with `http://` after `mplpb-net serve B --port 8801` and
`mplpb-net node describe B --endpoint http://host:8801/`, or with `zip://`
after `mplpb-net pack B b.zip` and a walk down the corridor. The answer and its
provenance do not change with the transport.

## Commands

```bash
# corpus
mplpb-net seed DIR --title T --scope S --terms a,b [--synonym a:x,y]
mplpb-net validate DIR                    # 16 checks; exit 1 on failure
mplpb-net spoke DIR NAME --title T --scope S
mplpb-net add DIR SPOKE --title T --scope S --text "..." [--origin machine --derived-from DOC-1]
mplpb-net supersede DIR DOC-ID --text "..." --reason "..."
mplpb-net copy SRC DST --relation mirror|descendant|fork|partial [--spokes a,b]
mplpb-net pack SRC out.zip ; mplpb-net unpack out.zip DST
mplpb-net build DIR                       # regenerate catalog, twin, manifest after hand edits

# node and hub
mplpb-net node init|seed|carry|describe|learn|refresh|known|forget ...
mplpb-net hub init|register|refresh|rebuild ...

# asking
mplpb-net route NODE "question"           # where, with scores; never answers
mplpb-net ask NODE "question" [--json]    # route, retrieve, verify, cite
mplpb-net cache-refresh NODE              # learn which cached pages were superseded

# running
mplpb-net serve NODE --port 8765          # static; never serves local/, known/, cache/, config
mplpb-net config show|set|check NODE ... ; mplpb-net config explain
mplpb-net experiment [--transport file|http] [--out DIR]
mplpb-net scale [--sizes 10,40,160]
```

## Replication relations

| Relation | Corpus ID | Meaning |
|---|---|---|
| `mirror` | same | byte-identical; must reproduce the source fingerprint |
| `descendant` | new | seeded from the source; owns a new domain |
| `fork` | new | seeded from the source; continues its domain under separate governance |
| `partial` | new | seeded from the source; keeps only the named spokes |

Every non-mirror records `seeded_from` (source ID and fingerprint) and appends
a hash-chained lineage event. Seeded-from is lineage, not endorsement. A corpus
may supersede only its own documents; a page that departs from another
corpus's records `diverges-from`.

## Configuration controls

`config.json` lives on the node, never in a corpus: the metadata travels, the
policy stays local. Every key changes observable behaviour and each has a test.

| Key | Default | Effect |
|---|---|---|
| `d_max` | `1` | greatest origin depth served |
| `ownership_margin` | `1.5` | leader must beat runner-up by this factor, else `ambiguous` |
| `min_scope_score` | `2.0` | below this a corpus owns nothing |
| `precedence` | `[]` | corpus IDs that win ambiguities; always reported in the note |
| `offline` | `false` | refuse network connectors; file and zip still work |
| `allow_connectors` | `file,zip,http` | which transports may be used at all |
| `timeout_seconds` | `5.0` | HTTP timeout |
| `verify` | `require` | `require` rejects, `warn` marks, `off` skips (testing only) |
| `stale_after_days` | `30` | descriptions older than this are reported stale and tried last |
| `max_hops` | `2` | hub-to-hub steps followed during discovery |
| `cache_remote` | `true` | keep retrieved pages with their envelopes |
| `include_retired` | `false` | allow retrieval to return retired pages, marked |

## Connectors

A connector reads a file at a relative path under an endpoint and never
interprets it. Verification does not depend on how the bytes arrived.

| Scheme | Class | Carries |
|---|---|---|
| `file://` | `FileConnector` | a directory on any mounted filesystem, share, or USB stick |
| `zip://` | `ZipConnector` | a node packed into an archive and carried by hand |
| `http://` | `HttpConnector` | any static web server pointed at the node; GET only |

A new transport is one class with a `read()` method and one line in
`connectors/__init__.py`.

## Layers

```
corpus.py        the seed: identity, lineage, manifest, catalog, spokes, pages, supersession
validate.py      16 checks, as findings not printout; the table also writes the prose rules
replicate.py     mirror / descendant / fork / partial; pack / unpack
node.py          Ed25519 identity; signed discovery descriptions; learning; staleness
hub.py           a corpus of descriptions; register, refresh, rebuild; no query-to-content path
router.py        declared-scope routing: vocabulary, margin, precedence, ambiguity
retrieve.py      static retrieval, envelopes, third-party verification, cache
connectors/      file, zip, http
config.py        twelve policy keys
server.py        optional static server for a node's public files
ed25519.py       RFC 8032, pure Python
experiment.py    Seed-to-Network, conditions A-H
scale.py         FM-N15 probe
```

Pages use the same metadata, `updated` format, supersession convention, and
`<!-- mplpb:entries -->` marker as the Smart Local front end, so a seed built
here passes that front end's eight checks and answers its `ask` command.

## The sixteen checks

| | Local (MPLPB-LOCAL-008 v4 §11) | | Network |
|---|---|---|---|
| 11.1 | link validity | N.1 | corpus identity, and the twin agrees |
| 11.2 | root reachability | N.2 | manifest integrity — every file, every hash |
| 11.3 | required metadata | N.3 | lineage hash chain |
| 11.4 | unique identity | N.4 | declared scope, terms in vocabulary |
| 11.5 | supersession consistency | N.5 | no keys or node files inside a corpus |
| 11.6 | boundary safety | N.6 | supersession scoped to this corpus |
| 11.7 | index consistency | N.7 | origin depth and recorded ratification |
| 11.8 | timestamp format | N.8 | seed completeness |

## The experiment

```bash
mplpb-net experiment --transport http --out Docs/results/http
```

Eight conditions: seed; replicate to three nodes; differentiate into kilns,
bees, bicycles, plus a fork of the bee corpus that genuinely collides with it;
discover through a hub; ask twelve graded queries; delete the hub; delete the
origin; carry a copy to a new node on a ZIP and rebuild a hub from what the
survivors hold. On both transports every metric in the reference run is 1.000
— routing, ambiguity preservation, provenance retention, offline retention,
replication integrity, origin independence, recovery — with zero non-stdlib
imports, 21 administrative actions, about three seconds and about 30 MB of memory.
Reports are in `Docs/results/`.

`mplpb-net scale` is less flattering, which is why it is here. At 10, 40, and
160 nodes, per-node hub registration costs 33, 48, and 120 ms: the reference
hub rehashes itself on every registration, so total registration is roughly
quadratic. Routing and registry size grow linearly.

## Tests

```bash
python3 -m unittest discover -s Tests -t .
```

61 tests, standard library `unittest`: the RFC 8032 vectors, every structural
check failing when it should, every replication relation, forged descriptions,
tampered pages, ambiguity, precedence, mirrors standing in for dead owners,
hub loss, hub rebuild, offline mode, HTTP with private directories refused,
supersession reaching caches, the laundering probe, each configuration key,
and one full run of the experiment.

## What this does not claim

Passing sixteen checks does not make a corpus true. A signature proves which
machine served a page, not that the page is right. Origin depth is
derivational distance, not reliability. The router measures the declarations;
a corpus that declares scope it cannot answer will be routed to anyway.

The reference run is a mechanical rehearsal: the corpora, queries, and code
share one author and one machine. A clean sweep there shows the implementation
does what the paper says. It does not show the paper is right. Three tests
would, and none has been run:

- **Blind stranger recovery.** People who have never seen the project are
  given one ZIP and ten written questions. `Docs/PROTOCOL.md` specifies it.
- **Ablation.** Same corpora, a hundred outside-written queries, declared-scope
  routing against flat BM25 over everything. If flat retrieval matches, the
  scope layer is decoration.
- **Adversaries.** A node can sign a false scope. A hub can omit entries.
  Anyone can claim an existing corpus ID; only node identity is bound to a key.

`ed25519.py` is correct against the RFC test vectors and is not constant-time
or audited. It gives tamper evidence, not protection from an attacker who can
time your CPU. The wire format is standard; swap in a vetted library if you
need that.

## Background

- `Docs/Networked_MPLPB.md` (`.txt`, `.pdf`) — the paper, revised with this implementation
- `Docs/PROTOCOL.md` — blind stranger-recovery and ablation protocols
- `Docs/lineage.md` — what came from where, and what changed
- *Smart Local MPLPB* — the front end this package's page format matches
- *The Local Mirror* — MPLPB as a self-contained offline site
- *Continuity Without Memory* (2026) — the collected specifications

## License

Code: MIT. Documentation, specification text, and the reference seed: CC BY
4.0. See `LICENSE`.

Mitchell D. McPhetridge
