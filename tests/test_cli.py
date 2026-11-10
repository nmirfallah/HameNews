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
        self.assertEqual(kw, {"subject": "Foo", "focus": None, "only": False})
        self.assertEqual(conf["discovery"]["topics_per_day"], 5)
        self.assertIsInstance(store, Store)
        self.assertEqual(store.root, self.data)
        self.assertEqual(get_llm.call_args[0][0]["provider"], "anthropic")
        op.assert_not_called()

    def test_http_library_request_logging_is_silenced(self):
        import logging
        for name in ("httpx", "httpcore", "anthropic"):
            logging.getLogger(name).setLevel(logging.INFO)
        with mock.patch.object(cli, "get_llm"), mock.patch.object(cli, "run", return_value=None):
            self.main("--config", CONFIG)
        for name in ("httpx", "httpcore", "anthropic"):
            self.assertGreaterEqual(logging.getLogger(name).level, logging.WARNING, name)

    def test_why_prints_the_explanation_without_needing_config_or_an_api_key(self):
        Store(self.data).write("discovery/2026-11-07.json", {"settings": {}, "signals": [], "clusters": []})
        out = io.StringIO()
        with mock.patch.object(cli, "get_llm", side_effect=AssertionError("must not be called")), \
                mock.patch.object(cli, "run", side_effect=AssertionError("must not run")), \
                contextlib.redirect_stdout(out):
            self.main("--why", "Iran")
        self.assertIn("No signal in that run mentions 'Iran'", out.getvalue())

    def test_why_without_a_log_explains_how_to_make_one(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.main("--why", "Iran")
        self.assertIn("no discovery log yet", out.getvalue())

    def test_the_error_helper_is_still_reachable_after_the_why_import(self):
        # regression: importing the explainer inside main() once shadowed the error helper of the same name
        with mock.patch.object(cli, "get_llm"), mock.patch.object(cli, "run", side_effect=FakeApiError(CREDIT, 400)):
            with self.assertRaises(SystemExit) as cm:
                self.main("--config", CONFIG)
        self.assertIn("credit balance is too low", str(cm.exception))

    def test_without_subject_it_runs_discovery(self):
        with mock.patch.object(cli, "get_llm"), mock.patch.object(cli, "run", return_value=None) as run:
            self.main("--config", CONFIG)
        self.assertEqual(run.call_args[1], {"subject": None, "focus": None, "only": False})

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


class JournalCliTests(unittest.TestCase):
    """-j SOURCE: analyse the news with that source included (--only: that source alone).
    --translation-only keeps the old per-source translation test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def main(self, *args):
        with mock.patch.object(sys, "argv", ["run.py", "--data-dir", self._tmp.name, "--config", CONFIG, *args]):
            cli.main()

    FOCUS = {"source": "irna.ir", "name": "IRNA", "found_via": "a feed", "items": [object()], "rows": []}
    RESULT = {"source": "irna.ir", "found_via": "x", "rows": [{"n": 1}], "path": "journal/irna-ir-2026-11-08.html",
              "summary": {}}

    def patched_focus(self, focus=None):
        import trendwatch.journal as j
        return mock.patch.object(j, "prepare_focus", return_value=focus or self.FOCUS)

    # --- the analysis
    def test_j_runs_the_real_analysis_with_the_source_as_the_focus(self):
        with self.patched_focus() as pf, mock.patch.object(cli, "get_llm"), \
                mock.patch.object(cli, "run", return_value="reports/x.md") as run:
            self.main("-j", "irna.ir")
        self.assertEqual(pf.call_args[0][3], "irna.ir")
        self.assertEqual(pf.call_args[1], {"lang": "", "limit": 40, "use_cache": True})
        (llm, conf, store), kw = run.call_args
        self.assertEqual(kw, {"subject": None, "focus": self.FOCUS, "only": False})
        self.assertTrue(conf["collection"]["sources"])           # normal sources stay on

    def test_only_switches_off_every_other_source_and_relaxes_the_minimum_items(self):
        with self.patched_focus(), mock.patch.object(cli, "get_llm"), \
                mock.patch.object(cli, "run", return_value="reports/x.md") as run:
            self.main("-j", "irna.ir", "--only")
        (_, conf, _), kw = run.call_args
        self.assertTrue(kw["only"])
        self.assertEqual(conf["collection"]["sources"], [])
        self.assertEqual(conf["news_sites"], [])
        self.assertFalse(conf["languages"]["search_native"])
        self.assertEqual(conf["analysis"]["min_items_to_analyze"], 4)

    def test_options_reach_the_focus_preparation_and_the_run(self):
        with self.patched_focus() as pf, mock.patch.object(cli, "get_llm"), \
                mock.patch.object(cli, "run", return_value=None) as run:
            self.main("--journal", "irna.ir", "--lang", "fa", "-n", "15", "--no-cache", "--subject", "Iran",
                      "--topics", "3")
        self.assertEqual(pf.call_args[1], {"lang": "fa", "limit": 15, "use_cache": False})
        (_, conf, _), kw = run.call_args
        self.assertEqual(kw["subject"], "Iran")
        self.assertEqual(conf["discovery"]["topics_per_day"], 3)

    def test_a_source_that_returns_nothing_stops_with_an_explanation(self):
        empty = dict(self.FOCUS, items=[], found_via="nothing")
        with self.patched_focus(empty), mock.patch.object(cli, "get_llm"), \
                mock.patch.object(cli, "run", side_effect=AssertionError("must not run")):
            with self.assertRaises(SystemExit) as cm:
                self.main("-j", "nope.example")
        self.assertIn("Nothing to translate", str(cm.exception))

    def test_open_opens_the_report_html(self):
        with self.patched_focus(), mock.patch.object(cli, "get_llm"), \
                mock.patch.object(cli, "run", return_value="reports/2026-11-09-irna-ir.md"), \
                mock.patch.object(cli.webbrowser, "open") as op, contextlib.redirect_stdout(io.StringIO()):
            self.main("-j", "irna.ir", "--open")
        self.assertTrue(op.call_args[0][0].endswith("2026-11-09-irna-ir.html"))

    def test_api_errors_while_preparing_the_source_get_the_short_message(self):
        import trendwatch.journal as j
        with mock.patch.object(j, "prepare_focus", side_effect=FakeApiError(CREDIT, 400)), mock.patch.object(cli, "get_llm"):
            with self.assertRaises(SystemExit) as cm:
                self.main("-j", "irna.ir")
        self.assertIn("credit balance is too low", str(cm.exception))

    def test_short_and_long_flags_are_the_same_option(self):
        with self.patched_focus() as pf, mock.patch.object(cli, "get_llm"), mock.patch.object(cli, "run", return_value=None):
            self.main("-j", "tasnimnews.ir")
            self.main("--journal", "tasnimnews.ir")
        self.assertEqual([c[0][3] for c in pf.call_args_list], ["tasnimnews.ir", "tasnimnews.ir"])

    # --- the translation test (previous behaviour of -j)
    def test_translation_only_runs_the_translation_test_and_not_the_analysis(self):
        import trendwatch.journal as j
        out = io.StringIO()
        with mock.patch.object(j, "run_journal", return_value=self.RESULT) as rj, \
                mock.patch.object(j, "render_text", return_value="REPORT TEXT"), mock.patch.object(cli, "get_llm"), \
                mock.patch.object(cli, "run", side_effect=AssertionError("must not analyse")), contextlib.redirect_stdout(out):
            self.main("-j", "irna.ir", "--translation-only")
        (_, _, _, source), kw = rj.call_args
        self.assertEqual((source, kw), ("irna.ir", {"subject": "", "lang": "", "limit": 10, "use_cache": True,
                                                    "do_verify": False}))
        self.assertIn("REPORT TEXT", out.getvalue())

    def test_translation_only_passes_every_option_and_can_open_the_page(self):
        import trendwatch.journal as j
        with mock.patch.object(j, "run_journal", return_value=self.RESULT) as rj, \
                mock.patch.object(j, "render_text", return_value="x"), mock.patch.object(cli, "get_llm"), \
                mock.patch.object(cli.webbrowser, "open") as op, contextlib.redirect_stdout(io.StringIO()):
            self.main("-j", "irna.ir", "--translation-only", "--subject", "Iran", "--lang", "fa", "-n", "5",
                      "--no-cache", "--verify", "--open")
        self.assertEqual(rj.call_args[1], {"subject": "Iran", "lang": "fa", "limit": 5, "use_cache": False,
                                           "do_verify": True})
        self.assertTrue(op.call_args[0][0].endswith("irna-ir-2026-11-08.html"))


class FakeApiError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


CREDIT = ("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': "
          "'Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing.'}}")


class ExplainTests(unittest.TestCase):
    def test_billing_error(self):
        msg = cli.explain(FakeApiError(CREDIT, 400))
        self.assertIn("credit balance is too low", msg)
        self.assertIn("Plans & Billing", msg)
        self.assertIn("chat subscription", msg)

    def test_bad_key(self):
        self.assertIn("API key was rejected", cli.explain(FakeApiError("nope", 401)))
        self.assertIn("API key was rejected", cli.explain(FakeApiError("invalid x-api-key")))

    def test_unknown_model(self):
        msg = cli.explain(FakeApiError("model: claude-x not found", 404))
        self.assertIn("config.yaml", msg)
        self.assertIsNone(cli.explain(FakeApiError("page not found", 404)))

    def test_rate_limit(self):
        self.assertIn("rate-limiting", cli.explain(FakeApiError("slow down", 429)))

    def test_missing_key_message_passes_through(self):
        err = RuntimeError("Set the ANTHROPIC_API_KEY environment variable.")
        self.assertEqual(cli.explain(err), str(err))

    def test_unknown_errors_are_not_explained_away(self):
        self.assertIsNone(cli.explain(ValueError("boom")))
        self.assertIsNone(cli.explain(FakeApiError("server exploded", 500)))


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def main(self):
        with mock.patch.object(sys, "argv", ["run.py", "--data-dir", self._tmp.name, "--config", CONFIG,
                                             "--subject", "Iran"]):
            cli.main()

    def test_billing_error_becomes_a_short_message_not_a_traceback(self):
        with mock.patch.object(cli, "get_llm"), mock.patch.object(cli, "run", side_effect=FakeApiError(CREDIT, 400)):
            with self.assertRaises(SystemExit) as cm:
                self.main()
        self.assertIn("credit balance is too low", str(cm.exception))

    def test_missing_key_is_caught_when_building_the_model(self):
        with mock.patch.object(cli, "get_llm", side_effect=RuntimeError("Set the ANTHROPIC_API_KEY environment variable.")):
            with self.assertRaises(SystemExit) as cm:
                self.main()
        self.assertIn("ANTHROPIC_API_KEY", str(cm.exception))

    def test_unexpected_errors_still_show_the_traceback(self):
        with mock.patch.object(cli, "get_llm"), mock.patch.object(cli, "run", side_effect=ValueError("bug")):
            with self.assertRaises(ValueError):
                self.main()


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
