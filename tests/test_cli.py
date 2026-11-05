import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import helpers
import run as cli
from trendwatch.store import Store

CONFIG = os.path.join(helpers.ROOT, "config.yaml")


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = self._tmp.name

    def main(self, *args):
        with mock.patch.object(sys, "argv", ["run.py", "--data-dir", self.data, *args]):
            cli.main()

    def make_report(self, name, mtime):
        path = os.path.join(self.data, "reports", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("x")
        os.utime(path, (mtime, mtime))
        return path

    def test_open_latest_opens_the_newest_html_report(self):
        self.make_report("a.html", 1000)
        newest = self.make_report("b.html", 2000)
        self.make_report("c.md", 3000)
        with mock.patch.object(cli.webbrowser, "open") as op, contextlib.redirect_stdout(io.StringIO()):
            self.main("--open-latest")
        (uri,), _ = op.call_args
        self.assertTrue(uri.startswith("file:"))
        self.assertTrue(uri.endswith("b.html"))
        self.assertIn("b.html", newest)

    def test_open_latest_without_reports_exits_with_a_hint(self):
        with self.assertRaises(SystemExit) as cm:
            self.main("--open-latest")
        self.assertIn("No reports yet", str(cm.exception))

    def test_streams_without_reconfigure_do_not_crash(self):
        self.make_report("a.html", 1000)
        with mock.patch.object(sys, "stdout", io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()), \
                mock.patch.object(cli.webbrowser, "open"):
            self.main("--open-latest")

    def test_subject_run_wires_config_store_and_topic_override(self):
        llm = object()
        with mock.patch.object(cli, "get_llm", return_value=llm) as get_llm, \
                mock.patch.object(cli, "run", return_value="reports/x.md") as run, \
                mock.patch.object(cli.webbrowser, "open") as op:
            self.main("--config", CONFIG, "--subject", "Foo", "--topics", "5")
        (got_llm, conf, store), kw = run.call_args
        self.assertIs(got_llm, llm)
        self.assertEqual(kw, {"subject": "Foo"})
        self.assertEqual(conf["discovery"]["topics_per_day"], 5)
        self.assertIsInstance(store, Store)
        self.assertEqual(store.root, self.data)
        self.assertEqual(get_llm.call_args[0][0]["provider"], "anthropic")
        op.assert_not_called()

    def test_without_subject_it_runs_discovery(self):
        with mock.patch.object(cli, "get_llm"), mock.patch.object(cli, "run", return_value=None) as run:
            self.main("--config", CONFIG)
        self.assertEqual(run.call_args[1], {"subject": None})

    def test_open_flag_opens_the_html_version_of_the_report(self):
        with mock.patch.object(cli, "get_llm"), mock.patch.object(cli, "run", return_value="reports/x.md"), \
                mock.patch.object(cli.webbrowser, "open") as op, contextlib.redirect_stdout(io.StringIO()):
            self.main("--config", CONFIG, "--open")
        self.assertTrue(op.call_args[0][0].endswith("x.html"))

    def test_open_flag_does_nothing_when_no_report_was_made(self):
        with mock.patch.object(cli, "get_llm"), mock.patch.object(cli, "run", return_value=None), \
                mock.patch.object(cli.webbrowser, "open") as op:
            self.main("--config", CONFIG, "--open")
        op.assert_not_called()


class CheckSourcesTests(unittest.TestCase):
    def test_show_reports_ok_empty_and_failures(self):
        import check_sources
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            check_sources.show("good", lambda: [helpers.item(1, text="hello")])
            check_sources.show("empty", lambda: [])
            check_sources.show("bad", lambda: 1 / 0)
        text = out.getvalue()
        self.assertIn("ok   good: 1 results", text)
        self.assertIn("EMPTY empty: 0 results", text)
        self.assertIn("FAIL  bad: ZeroDivisionError", text)
        self.assertIn("hello", text)


if __name__ == "__main__":
    unittest.main()
