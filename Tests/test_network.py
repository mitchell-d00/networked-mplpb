import json

from mplpb_net import config as cfgmod
from mplpb_net import hub as hubmod
from mplpb_net.connectors import Unavailable, connect
from mplpb_net.corpus import supersede
from mplpb_net.node import Node, verify_description
from mplpb_net.retrieve import ask, refresh_cache, verify_envelope
from mplpb_net.router import route
from mplpb_net.server import is_public, serve_in_thread
from mplpb_net.util import read_json

from .support import TempTest

KILN = ("Kiln Notes", "Kiln firing schedules and glaze chemistry", ["kiln", "glaze", "firing"],
        {"kiln": ["furnace"]},
        [("Bisque firing", "Bisque firing schedule", "Fire slowly to 1000 C, 100 C per hour.")])
BEES = ("Apiary", "Beekeeping: hive inspection and honey", ["beekeeping", "hive", "honey"],
        {"beekeeping": ["bees"]},
        [("Hive inspection", "Routine hive inspection", "Inspect every seven to ten days.")])
BEES2 = ("Rooftop Apiary", "Rooftop beekeeping: hive placement and honey", ["beekeeping", "hive", "honey", "rooftop"],
         {"beekeeping": ["bees"]},
         [("Rooftop hive", "Hive placement on a roof", "Use a windbreak on a rooftop hive.")])


class Network(TempTest):
    def setUp(self):
        super().setUp()
        self.A = Node.init(self.tmp / "A", "a")
        self.seedc = self.A.seed(title="Seed", scope="Networked corpus format, validation and provenance",
                                 scope_terms=["corpus", "validation", "provenance"], owner="T")
        self.B, self.kiln = self.domain_node("B", self.seedc.root, *KILN)
        self.C, self.bees = self.domain_node("C", self.seedc.root, *BEES)
        self.D, self.bees2 = self.domain_node("D", self.seedc.root, *BEES2)
        self.H = hubmod.init_hub(self.tmp / "H", "hub")
        for n in (self.A, self.B, self.C, self.D):
            hubmod.register(self.H, n.root.as_uri())
        self.A.learn(self.H.root.as_uri())


class Identity(Network):
    def test_description_verifies(self):
        ok, why = verify_description(self.B.description)
        self.assertTrue(ok, why)

    def test_forged_identity_rejected(self):
        d = dict(self.B.description)
        d["public_key"] = self.C.public_hex  # claim B's ID with C's key
        self.assertFalse(verify_description(d)[0])
        d = dict(self.B.description)
        d["name"] = "impostor"
        self.assertFalse(verify_description(d)[0])

    def test_hub_refuses_forged_description(self):
        d = dict(self.B.description)
        d["corpora"] = []
        with self.assertRaises(Unavailable):
            hubmod.register_description(self.H, d)

    def test_learned_everyone_through_hub(self):
        known = {d["node_id"] for d, _ in self.A.known()}
        self.assertTrue({self.B.node_id, self.C.node_id, self.D.node_id} <= known)


class Routing(Network):
    def test_local(self):
        self.assertEqual(route(self.A, "how is corpus validation done").kind, "local")

    def test_remote_single_owner(self):
        r = route(self.A, "bisque firing schedule for a kiln")
        self.assertEqual((r.kind, r.owner.corpus_id), ("remote", self.kiln.corpus_id))

    def test_synonym_from_vocabulary(self):
        r = route(self.A, "furnace temperature")
        self.assertEqual(r.owner.corpus_id, self.kiln.corpus_id)

    def test_ambiguity_reported_not_merged(self):
        r = route(self.A, "hive inspection for honey bees")
        self.assertEqual(r.kind, "ambiguous")
        self.assertEqual({c.corpus_id for c in r.contenders}, {self.bees.corpus_id, self.bees2.corpus_id})
        a = ask(self.A, "hive inspection for honey bees")
        self.assertIsNone(a.envelope)

    def test_precedence_resolves_ambiguity_and_says_so(self):
        cfgmod.set_value(self.A.root, "precedence", self.bees.corpus_id)
        r = route(self.A, "hive inspection for honey bees")
        self.assertEqual(r.owner.corpus_id, self.bees.corpus_id)
        self.assertIn("precedence", r.note)

    def test_not_found(self):
        self.assertEqual(route(self.A, "sourdough starter").kind, "not_found")

    def test_hub_is_never_an_owner(self):
        r = route(self.A, "discovery registry of nodes")
        self.assertNotEqual(r.kind, "remote")


class Provenance(Network):
    def test_remote_envelope_verifies_and_names_source(self):
        a = ask(self.A, "bisque firing schedule for a kiln")
        self.assertEqual(a.kind, "remote")
        env = a.envelope
        self.assertTrue(env["verified"])
        self.assertEqual(env["corpus_id"], self.kiln.corpus_id)
        self.assertEqual(env["served_by"]["node_id"], self.B.node_id)
        self.assertEqual([h["role"] for h in env["route"]], ["requester", "discovery", "server"])
        self.assertEqual(env["route"][1]["node_id"], self.H.node_id)
        arts = self.A.root / "cache" / "_artifacts"
        manifest = read_json(arts / f"manifest-{env['manifest_sha256'][:24]}.json")
        desc = read_json(arts / f"description-{env['served_by']['description_sha256'][:24]}.json")
        page = (self.A.root / "cache" / env["corpus_id"] / env["path"]).read_bytes()
        cached_env = read_json(self.A.root / "cache" / env["corpus_id"] / (env["path"] + ".envelope.json"))
        self.assertEqual(verify_envelope(cached_env, page, manifest, desc), (True, "ok"))
        self.assertEqual(verify_envelope(cached_env, page + b"x", manifest, desc)[0], False)
        forged = dict(cached_env, corpus_id=self.bees.corpus_id)
        self.assertFalse(verify_envelope(forged, page, manifest, desc)[0])

    def test_tampered_remote_page_refused(self):
        p = self.kiln.root / "main" / "bisque_firing.html"
        p.write_text(p.read_text().replace("1000", "1300"))
        a = ask(self.A, "bisque firing schedule for a kiln")
        self.assertEqual(a.kind, "unavailable")
        self.assertIn("verification failed", a.tried[0][1])

    def test_warn_mode_accepts_but_marks(self):
        p = self.kiln.root / "main" / "bisque_firing.html"
        p.write_text(p.read_text().replace("1000", "1300"))
        cfgmod.set_value(self.A.root, "verify", "warn")
        a = ask(self.A, "bisque firing schedule for a kiln")
        self.assertEqual(a.kind, "remote")
        self.assertFalse(a.envelope["verified"])

    def test_unavailable_is_not_impersonated(self):
        import shutil
        shutil.rmtree(self.B.root)
        a = ask(self.A, "bisque firing schedule for a kiln")
        self.assertEqual(a.kind, "unavailable")
        self.assertIn("Relevant corpus known; node unavailable", a.render())

    def test_mirror_serves_with_honest_citation(self):
        E = Node.init(self.tmp / "E", "e")
        E.carry(self.kiln.root, "mirror")
        hubmod.register(self.H, E.root.as_uri())
        self.A.learn(self.H.root.as_uri())
        import shutil
        kiln_id = self.kiln.corpus_id
        shutil.rmtree(self.B.root)
        a = ask(self.A, "bisque firing schedule for a kiln")
        self.assertEqual(a.kind, "remote")
        self.assertEqual(a.envelope["corpus_id"], kiln_id)
        self.assertEqual(a.envelope["served_by"]["node_id"], E.node_id)
        self.assertIn("mirror", a.note)

    def test_depth_policy_withholds(self):
        from mplpb_net.corpus import add_page
        add_page(self.kiln.root, "main", title="Kiln machine digest", text="bisque firing kiln digest schedule",
                 scope="bisque firing kiln schedule digest", origin="machine", origin_depth=3)
        self.B.describe()
        cfgmod.set_value(self.A.root, "d_max", "1")
        self.A.refresh()
        a = ask(self.A, "kiln bisque firing schedule digest")
        self.assertLessEqual(a.envelope["origin_depth"], 1)
        self.assertGreaterEqual(a.withheld, 1)

    def test_supersession_propagates_to_cache_without_deleting(self):
        ask(self.A, "bisque firing schedule for a kiln")
        supersede(self.kiln.root, "MAIN-001", text="Fire slowly; hold ten minutes.", reason="hold")
        self.B.describe()
        changes = refresh_cache(self.A)
        self.assertEqual(changes[0]["document_id"], "MAIN-001")
        self.assertTrue((self.A.root / "cache" / self.kiln.corpus_id / "main" / "bisque_firing.html").exists())


class Resilience(Network):
    def test_hub_loss_keeps_local_and_known_peers(self):
        import shutil
        shutil.rmtree(self.H.root)
        self.assertEqual(ask(self.A, "corpus validation").kind, "local")
        self.assertEqual(ask(self.A, "bisque firing schedule for a kiln").kind, "remote")

    def test_offline_blocks_network_only(self):
        cfgmod.set_value(self.A.root, "offline", "true")
        with self.assertRaises(Unavailable):
            connect("http://127.0.0.1:9/", self.A.cfg)
        connect(self.B.root.as_uri(), self.A.cfg)  # file still fine
        self.assertEqual(ask(self.A, "corpus validation").kind, "local")

    def test_allow_connectors(self):
        cfgmod.set_value(self.A.root, "allow_connectors", "zip")
        self.assertEqual(ask(self.A, "bisque firing schedule for a kiln").kind, "unavailable")

    def test_rebuild_hub_from_survivors(self):
        import shutil
        shutil.rmtree(self.H.root)
        H2, count = hubmod.rebuild(self.tmp / "H2", "hub2", [self.B.root, self.C.root, self.A.root])
        self.assertGreaterEqual(count, 3)
        E = Node.init(self.tmp / "E", "e")
        E.learn(H2.root.as_uri())
        self.assertEqual(ask(E, "bisque firing schedule for a kiln").kind, "remote")

    def test_stale_marked(self):
        cfgmod.set_value(self.A.root, "stale_after_days", "0")
        r = route(self.A, "bisque firing schedule for a kiln")
        self.assertTrue(all(h.stale for h in r.owner.holders if not h.local))

    def test_cache_off(self):
        cfgmod.set_value(self.A.root, "cache_remote", "false")
        ask(self.A, "bisque firing schedule for a kiln")
        self.assertFalse((self.A.root / "cache" / self.kiln.corpus_id).exists())

    def test_hub_reregistration_supersedes(self):
        self.B.describe(["file:///elsewhere"])
        self.assertEqual(hubmod.register(self.H, self.B.root.as_uri()), "updated")
        hc = hubmod.hub_corpus(self.H)
        from mplpb_net.validate import validate
        self.assertTrue(validate(hc.root).ok, validate(hc.root).summary())
        self.assertTrue(any(p.status == "retired" for p in hc.pages().values()))


class Http(Network):
    def test_http_transport_and_private_dirs(self):
        srv, url = serve_in_thread(self.B.root)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.B.describe([url])
        E = Node.init(self.tmp / "E", "e")
        E.learn(url)
        a = ask(E, "bisque firing schedule for a kiln")
        self.assertEqual(a.kind, "remote")
        self.assertTrue(a.envelope["served_by"]["endpoint"].startswith("http://"))
        with self.assertRaises(Unavailable):
            connect(url).read("local/node.key")
        with self.assertRaises(Unavailable):
            connect(url).read("config.json")

    def test_is_public(self):
        self.assertTrue(is_public("/node.json"))
        self.assertTrue(is_public("/corpora/C-1/index.html"))
        self.assertFalse(is_public("/local/node.key"))
        self.assertFalse(is_public("/../etc/passwd"))


class Config(TempTest):
    def test_every_key_exercised(self):
        # Each key is exercised by a behavioural test above; this guards the list.
        exercised = {"d_max", "ownership_margin", "min_scope_score", "precedence", "offline",
                     "allow_connectors", "timeout_seconds", "verify", "stale_after_days",
                     "max_hops", "cache_remote", "include_retired"}
        self.assertEqual(set(cfgmod.SCHEMA), exercised)

    def test_bad_values_rejected(self):
        n = Node.init(self.tmp / "n", "n")
        with self.assertRaises(ValueError):
            cfgmod.set_value(n.root, "verify", "sometimes")
        with self.assertRaises(ValueError):
            cfgmod.set_value(n.root, "ownership_margin", "0.5")
        with self.assertRaises(KeyError):
            cfgmod.set_value(n.root, "nonsense", "1")


class MarginAndScore(Network):
    def test_margin_changes_outcome(self):
        q = "rooftop hive"
        self.assertEqual(route(self.A, q).kind, "remote")
        cfgmod.set_value(self.A.root, "ownership_margin", "3")
        self.assertEqual(route(self.A, q).kind, "ambiguous")

    def test_min_score_changes_outcome(self):
        cfgmod.set_value(self.A.root, "min_scope_score", "50")
        self.assertEqual(route(self.A, "bisque firing kiln").kind, "not_found")

    def test_include_retired(self):
        supersede(self.kiln.root, "MAIN-001", text="Completely different words now.", reason="r")
        self.B.describe()
        self.A.refresh()
        cfgmod.set_value(self.A.root, "include_retired", "true")
        a = ask(self.A, "kiln fire slowly 1000")
        self.assertEqual(a.envelope["status"], "retired")

    def test_max_hops_zero_stops_hub_chain(self):
        H2 = hubmod.init_hub(self.tmp / "H2", "hub2")
        hubmod.register(H2, self.H.root.as_uri())  # H2 knows hub H
        E = Node.init(self.tmp / "E", "e")
        cfgmod.set_value(E.root, "max_hops", "0")
        E.learn(H2.root.as_uri())
        self.assertNotIn(self.B.node_id, {d["node_id"] for d, _ in E.known()})
        E2 = Node.init(self.tmp / "E2", "e2")
        E2.learn(H2.root.as_uri())
        self.assertIn(self.B.node_id, {d["node_id"] for d, _ in E2.known()})

    def test_timeout_used(self):
        c = connect("http://10.255.255.1:9/", {"timeout_seconds": 0.2})
        self.assertEqual(c.timeout, 0.2)
