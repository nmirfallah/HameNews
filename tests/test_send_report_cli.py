import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import helpers
import run as run_cli
import send_report as cli
from trendwatch import emailer


class SendReportCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.data = os.path.join(self.dir, "data")
        self.yaml = os.path.join(self.dir, "emails.yaml")
        with open(self.yaml, "w", encoding="utf-8") as f:
            f.write("recipients: [a@example.com]\n")
        base = os.path.join(self.data, "reports", "2026-11-10")
        os.makedirs(os.path.dirname(base))
        for ext, text in ((".json", json.dumps([{"topic": "Midterms"}])), (".md", "# md"), (".html", "<p>full</p>"),
                          (".email.html", "<p>mail</p>")):
            with open(base + ext, "w", encoding="utf-8") as f:
                f.write(text)

    def main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--recipients", self.yaml, "--data-dir", self.data, *args])
        return out.getvalue()

    def test_dry_run_prints_what_would_be_sent_and_where_the_preview_is(self):
        text = self.main("--dry-run")
        self.assertIn("Dry run: nothing was sent.", text)
        self.assertIn("HameNews 2026-11-10: Midterms", text)
        self.assertIn("a@example.com", text)
        self.assertIn("HameNews-2026-11-10.html", text)
        self.assertIn("email-preview.html", text)

    def test_a_real_send_reports_who_got_it(self):
        with mock.patch.object(cli, "send_report", return_value={"sent": 2, "recipients": ["a@x.com", "b@x.com"],
                                                                   "subject": "S"}) as sr:
            text = self.main("--to", "a@x.com", "--date", "2026-11-10")
        self.assertEqual(sr.call_args[1], {"day": "2026-11-10", "to": "a@x.com", "dry_run": False})
        self.assertIn("Sent to 2 recipient(s): a@x.com, b@x.com", text)

    def test_a_switched_off_file_says_so_and_exits_normally(self):
        with open(self.yaml, "w", encoding="utf-8") as f:
            f.write("enabled: false\nrecipients: [a@example.com]\n")
        self.assertIn("switched off", self.main())

    def test_problems_become_a_short_error_and_a_failing_exit_code(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as cm:
                self.main()                 # real run without credentials
        self.assertIn("SMTP_USERNAME", str(cm.exception))
        self.assertTrue(str(cm.exception).startswith("Error:"))

    def test_a_bad_recipients_file_is_reported(self):
        with open(self.yaml, "w", encoding="utf-8") as f:
            f.write("recipients: [nope]\n")
        with self.assertRaises(SystemExit) as cm:
            self.main("--dry-run")
        self.assertIn("nope", str(cm.exception))


class RunEmailFlagTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def main(self, *args):
        import sys
        with mock.patch.object(sys, "argv", ["run.py", "--data-dir", self._tmp.name,
                                             "--config", os.path.join(helpers.ROOT, "config.yaml"), *args]):
            run_cli.main()

    def test_email_sends_after_a_successful_run_using_emails_yaml_next_to_the_config(self):
        with mock.patch.object(run_cli, "get_llm"), mock.patch.object(run_cli, "run", return_value="reports/x.md"), \
                mock.patch.object(emailer, "send_report", return_value={"sent": 1, "recipients": ["a@x.com"]}) as sr, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.main("--email")
        (data_dir, path), _ = sr.call_args
        self.assertEqual(data_dir, self._tmp.name)
        self.assertEqual(path, os.path.join(helpers.ROOT, "emails.yaml"))
        self.assertIn("Emailed 1 recipient(s): a@x.com", out.getvalue())

    def test_nothing_is_emailed_when_no_report_was_made_or_the_flag_is_absent(self):
        for flags, result in (([], "reports/x.md"), (["--email"], None)):
            with mock.patch.object(run_cli, "get_llm"), mock.patch.object(run_cli, "run", return_value=result), \
                    mock.patch.object(emailer, "send_report") as sr:
                self.main(*flags)
            sr.assert_not_called()

    def test_email_problems_end_with_a_short_message(self):
        with mock.patch.object(run_cli, "get_llm"), mock.patch.object(run_cli, "run", return_value="reports/x.md"), \
                mock.patch.object(emailer, "send_report", side_effect=emailer.EmailError("Missing SMTP_PASSWORD.")):
            with self.assertRaises(SystemExit) as cm:
                self.main("--email")
        self.assertIn("Missing SMTP_PASSWORD", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
