"""Shared fixtures: small nodes and corpora in a temp directory."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from mplpb_net.corpus import add_page, add_spoke, create_seed
from mplpb_net.node import Node


class TempTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mplpb-net-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def seed(self, name="seed", **kw):
        kw.setdefault("title", "Test Seed")
        kw.setdefault("scope", "Networked corpus format, validation and provenance")
        kw.setdefault("scope_terms", ["corpus", "validation", "provenance"])
        kw.setdefault("owner", "Tester")
        return create_seed(self.tmp / name, **kw)

    def domain_node(self, label, src, title, scope, terms, vocab=None, pages=()):
        n = Node.init(self.tmp / label, label)
        c = n.carry(src, "descendant", title=title, scope=scope, scope_terms=terms, vocabulary=vocab or {})
        add_spoke(c.root, "main", title=title, scope=scope, build=False)
        for t, s, text in pages:
            add_page(c.root, "main", title=t, scope=s, text=text, build=False)
        c.build()
        n.describe()
        return n, n.corpus(c.corpus_id)
