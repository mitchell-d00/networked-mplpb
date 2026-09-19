import json
import shutil

from mplpb_net.corpus import Corpus, add_page, add_spoke, supersede
from mplpb_net.page import Page
from mplpb_net.replicate import ReplicationError, copy_corpus, pack, unpack
from mplpb_net.validate import CHECKS, validate

from .support import TempTest


class Seed(TempTest):
    def test_fresh_seed_validates(self):
        r = validate(self.seed().root)
        self.assertTrue(r.ok, r.summary())

    def test_validation_prose_covers_every_check(self):
        text = (self.seed().root / "spec" / "validation.html").read_text()
        for cid, (title, _, _) in CHECKS.items():
            self.assertIn(cid, text)

    def test_growth_keeps_validity(self):
        c = self.seed()
        add_spoke(c.root, "kiln", title="Kiln", scope="Firing")
        add_page(c.root, "kiln", title="Bisque", text="Slowly.", scope="Bisque firing")
        self.assertTrue(validate(c.root).ok)

    def test_supersession_retires_not_deletes(self):
        c = self.seed()
        add_spoke(c.root, "kiln", title="Kiln", scope="Firing")
        add_page(c.root, "kiln", title="Bisque", text="Old.", scope="Bisque firing")
        new = supersede(c.root, "KILN-001", text="New.", reason="better")
        self.assertEqual(new.version, 2)
        retired = [p for p in c.pages().values() if p.status == "retired"]
        self.assertEqual(len(retired), 1)
        self.assertIn("Old.", retired[0].text)
        self.assertTrue(validate(c.root).ok)

    def test_cannot_supersede_foreign_document(self):
        c = self.seed()
        with self.assertRaises(PermissionError):
            supersede(c.root, "C-OTHER0000000:DOC-1", text="x", reason="x")


class Integrity(TempTest):
    def test_tamper_detected(self):
        c = self.seed()
        p = c.root / "spec" / "seed.html"
        p.write_text(p.read_text().replace("Open it", "Open it quickly"))
        self.assertIn("N.2", validate(c.root).failed())

    def test_unlisted_file_detected(self):
        c = self.seed()
        (c.root / "extra.txt").write_text("hi")
        self.assertIn("N.2", validate(c.root).failed())

    def test_stale_twin_detected(self):
        c = self.seed()
        ident = json.loads((c.root / "_net/corpus.json").read_text())
        ident["scope"] = "something else"
        (c.root / "_net/corpus.json").write_text(json.dumps(ident))
        Corpus(c.root).build_manifest()
        self.assertIn("N.1", validate(c.root).failed())

    def test_broken_lineage_chain_detected(self):
        c = self.seed()
        lin = json.loads((c.root / "_net/lineage.json").read_text())
        lin["events"].append({"seq": 1, "event": "x", "corpus_id": c.corpus_id, "at": "", "detail": {}, "prev": "bad"})
        (c.root / "_net/lineage.json").write_text(json.dumps(lin))
        Corpus(c.root).build_manifest()
        self.assertIn("N.3", validate(c.root).failed())

    def test_key_inside_corpus_rejected(self):
        c = self.seed()
        (c.root / "node.key").write_text("00")
        Corpus(c.root).build_manifest()
        self.assertIn("N.5", validate(c.root).failed())

    def test_missing_seed_guide_detected(self):
        c = self.seed()
        (c.root / "spec" / "seed.html").unlink()
        self.assertIn("N.8", validate(c.root).failed())


class OriginDepth(TempTest):
    def setUp(self):
        super().setUp()
        self.c = self.seed()
        add_spoke(self.c.root, "notes", title="Notes", scope="Notes")
        add_page(self.c.root, "notes", title="Human", text="h", scope="human page")

    def test_machine_depth_derived(self):
        p = add_page(self.c.root, "notes", title="M1", text="m", scope="m", origin="machine", derived_from=["NOTES-001"])
        self.assertEqual(p.origin_depth, 1)
        p2 = add_page(self.c.root, "notes", title="M2", text="m", scope="m", origin="machine", derived_from=[p.document_id])
        self.assertEqual(p2.origin_depth, 2)
        self.assertTrue(validate(self.c.root).ok)

    def test_unknown_remote_source_is_conservative(self):
        p = add_page(self.c.root, "notes", title="R", text="r", scope="r", origin="machine", derived_from=["C-XYZ:DOC-9"])
        self.assertEqual(p.origin_depth, 2)

    def test_understated_depth_rejected(self):
        add_page(self.c.root, "notes", title="M1", text="m", scope="m", origin="machine", derived_from=["NOTES-001"])
        add_page(self.c.root, "notes", title="M2", text="m", scope="m", origin="machine", origin_depth=1,
                 derived_from=["NOTES-002"])
        self.assertIn("N.7", validate(self.c.root).failed())

    def test_ratification_must_be_recorded(self):
        with self.assertRaises(ValueError):
            add_page(self.c.root, "notes", title="Rat", text="x", scope="x", origin="ratified")
        p = add_page(self.c.root, "notes", title="Rat", text="x", scope="x", origin="ratified", ratified_by="Editor")
        self.assertEqual(p.origin_depth, 0)
        self.assertTrue(validate(self.c.root).ok)


class Replication(TempTest):
    def test_mirror_is_byte_identical(self):
        c = self.seed()
        m = copy_corpus(c.root, self.tmp / "m", "mirror")
        self.assertEqual(m.corpus_id, c.corpus_id)
        self.assertEqual(m.manifest_sha256, c.manifest_sha256)

    def test_descendant_records_lineage_not_endorsement(self):
        c = self.seed()
        d = copy_corpus(c.root, self.tmp / "d", "descendant", title="Kiln", scope="Kilns", scope_terms=["kiln"])
        ident = d.identity
        self.assertNotEqual(ident["corpus_id"], c.corpus_id)
        self.assertEqual(ident["seeded_from"]["corpus_id"], c.corpus_id)
        self.assertEqual(ident["seeded_from"]["manifest_sha256"], c.manifest_sha256)
        self.assertEqual(d.lineage[-1]["event"], "descendant")
        self.assertTrue(validate(d.root).ok)

    def test_partial_keeps_only_named_spokes(self):
        c = self.seed()
        add_spoke(c.root, "a", title="A", scope="a")
        add_spoke(c.root, "b", title="B", scope="b")
        p = copy_corpus(c.root, self.tmp / "p", "partial", spokes=["a"])
        self.assertTrue((p.root / "a").exists())
        self.assertFalse((p.root / "b").exists())
        self.assertTrue(validate(p.root).ok)

    def test_refuses_corrupt_source(self):
        c = self.seed()
        (c.root / "index.html").write_text((c.root / "index.html").read_text() + " ")
        with self.assertRaises(ReplicationError):
            copy_corpus(c.root, self.tmp / "x", "mirror")

    def test_sneakernet_round_trip(self):
        c = self.seed()
        z = pack(c.root, self.tmp / "carry.zip")
        out = unpack(z, self.tmp / "unpacked")
        self.assertEqual(Corpus(out).compute_manifest()["manifest_sha256"], c.manifest_sha256)
        self.assertTrue(validate(out).ok)

    def test_readable_by_smart_local_page_format(self):
        c = self.seed()
        page = Page.load(c.root / "index.html", c.root)
        self.assertEqual(page.document_id, "NET-MAIN-000")
        self.assertEqual(page.status, "current")
