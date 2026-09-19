import io
import contextlib

from mplpb_net.__main__ import main
from mplpb_net.experiment import run

from .support import TempTest


class Experiment(TempTest):
    def test_all_conditions_pass_on_reference_run(self):
        res = run("file", workdir=self.tmp / "exp")
        for key, value in res["metrics"].items():
            self.assertTrue(value is True or value == 1.0, f"{key} = {value}")
        self.assertTrue(res["burden"]["stdlib_only"], res["burden"]["non_stdlib_imports"])


class Cli(TempTest):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main([str(a) for a in argv])
        return code, buf.getvalue()

    def test_seed_grow_validate_copy(self):
        s = self.tmp / "s"
        self.assertEqual(self.run_cli("seed", s, "--title", "T", "--scope", "Kilns", "--terms", "kiln",
                                      "--synonym", "kiln:furnace")[0], 0)
        self.assertEqual(self.run_cli("spoke", s, "kiln", "--title", "Kiln", "--scope", "Firing")[0], 0)
        self.assertEqual(self.run_cli("add", s, "kiln", "--title", "Bisque", "--scope", "Bisque",
                                      "--text", "Slowly.")[0], 0)
        code, out = self.run_cli("validate", s)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.run_cli("copy", s, self.tmp / "d", "--relation", "descendant",
                                      "--title", "D", "--scope", "Glazes", "--terms", "glaze")[0], 0)
        self.assertEqual(self.run_cli("validate", self.tmp / "d")[0], 0)

    def test_node_hub_ask(self):
        a, b, h = self.tmp / "a", self.tmp / "b", self.tmp / "h"
        self.run_cli("node", "init", a, "--name", "a")
        self.run_cli("node", "seed", a, "--title", "Seed", "--scope", "Corpus rules", "--terms", "corpus")
        self.run_cli("node", "init", b, "--name", "b")
        seed_dir = next((a / "corpora").iterdir())
        self.run_cli("node", "carry", b, seed_dir, "--relation", "descendant", "--title", "Kiln",
                     "--scope", "Kiln firing", "--terms", "kiln,firing")
        kiln = [p for p in (b / "corpora").iterdir()][0]
        self.run_cli("spoke", kiln, "k", "--title", "K", "--scope", "Kiln firing")
        self.run_cli("add", kiln, "k", "--title", "Bisque", "--scope", "Bisque firing", "--text", "Slow kiln firing.")
        self.run_cli("node", "describe", b)
        self.run_cli("hub", "init", h, "--name", "h")
        self.run_cli("hub", "register", h, b.as_uri())
        self.run_cli("node", "learn", a, h.as_uri())
        code, out = self.run_cli("ask", a, "kiln bisque firing")
        self.assertEqual(code, 0, out)
        self.assertIn("route:", out)
        code, out = self.run_cli("route", a, "sourdough")
        self.assertIn("not_found", out)
        self.assertEqual(self.run_cli("config", "set", a, "d_max", "0")[0], 0)
