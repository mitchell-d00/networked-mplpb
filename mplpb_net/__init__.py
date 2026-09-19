"""
Networked MPLPB -- grow a knowledge network from a seed.

Standard library only. A seed is a bounded corpus of plain HTML that carries
enough of its own organization to be copied onto another machine and remain
interpretable there. A node is a machine that carries corpora and publishes a
signed description of them. A hub is a node whose corpus lists other nodes.

    corpus.py      the seed: identity, lineage, manifest, catalog, growth
    validate.py    16 structural checks (11.1-11.8 local, N.1-N.8 network)
    replicate.py   mirror / descendant / fork / partial; pack / unpack
    node.py        node identity (Ed25519), signed discovery descriptions
    hub.py         a corpus of corpus descriptions; never answers
    router.py      routing by declared scope; ambiguity is reported
    retrieve.py    static retrieval with verifiable provenance envelopes
    connectors/    file, zip (sneakernet), http -- transport is replaceable
    config.py      local policy: d_max, margins, offline, verification...
    server.py      optional static HTTP server for a node's public files
    experiment.py  the Seed-to-Network experiment, conditions A-H
    scale.py       discovery cost as the registry grows (FM-N15 probe)
"""

__version__ = "0.1.0"
