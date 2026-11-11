import email
import json
import os
import smtplib
import tempfile
import unittest
import unittest.mock
from email import policy

import helpers
from trendwatch import emailer
from trendwatch.emailer import EmailError

ENV = {"SMTP_USERNAME": "sender@gmail.com", "SMTP_PASSWORD": "abcd efgh ijkl mnop"}


def write(path, text="", binary=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as f:
        f.write(text)


class FakeServer:
    def __init__(self, log, fail_login=None, fail_send=None):
        self.log, self.fail_login, self.fail_send = log, fail_login, fail_send

    def login(self, user, password):
        self.log.append(("login", user, password))
        if self.fail_login:
            raise self.fail_login

    def send_message(self, message):
        if self.fail_send:
            raise self.fail_send
        self.log.append(("send", message))

    def quit(self):
        self.log.append(("quit",))


def fake_connect(log, **kw):
    def connect(host, port, use_ssl):
        log.append(("connect", host, port, use_ssl))
        if kw.get("fail_connect"):
            raise kw["fail_connect"]
        return FakeServer(log, kw.get("fail_login"), kw.get("fail_send"))
    return connect


class FilesCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.data = os.path.join(self.dir, "data")
        self.yaml = os.path.join(self.dir, "emails.yaml")

    def settings(self, text):
        write(self.yaml, text)
        return self.yaml

    def report(self, day="2026-11-10", topics=("Midterms", "Krakow shooting"), email_html=True, md=True, html=True):
        base = os.path.join(self.data, "reports", day)
        write(base + ".json", json.dumps([{"topic": t, "rank": i} for i, t in enumerate(topics, 1)]))
        if md:
            write(base + ".md", "# HameNews\n\nplain text body é")
        if html:
            write(base + ".html", "<html>full report é</html>")
        if email_html:
            write(base + ".email.html", "<html>email body é</html>")
        return base


class LoadSettingsTests(FilesCase):
    def test_the_shipped_file_has_the_requested_recipient(self):
        s = emailer.load_settings(os.path.join(helpers.ROOT, "emails.yaml"))
        self.assertEqual([r["address"] for r in s["recipients"]], ["s.n.mirfallah@gmail.com"])
        self.assertTrue(s["enabled"])
        self.assertEqual(s["attach"], ["html"])

    def test_defaults_apply_to_a_minimal_file(self):
        s = emailer.load_settings(self.settings("recipients: [a@example.com]"))
        self.assertEqual((s["enabled"], s["subject_prefix"], s["topics_in_subject"], s["attach"]),
                         (True, "HameNews", 3, ["html"]))

    def test_strings_and_name_address_entries_are_both_accepted(self):
        s = emailer.load_settings(self.settings(
            "recipients:\n  - a@example.com\n  - address: b@example.com\n    name: Bea Smith\n  - ''\n  -\n"))
        self.assertEqual(s["recipients"], [{"address": "a@example.com", "name": ""},
                                           {"address": "b@example.com", "name": "Bea Smith"}])

    def test_duplicates_are_removed_ignoring_case(self):
        s = emailer.load_settings(self.settings("recipients: [A@Example.com, a@example.com, b@example.com]"))
        self.assertEqual([r["address"] for r in s["recipients"]], ["A@Example.com", "b@example.com"])

    def test_invalid_addresses_stop_everything_and_are_all_listed(self):
        with self.assertRaises(EmailError) as cm:
            emailer.load_settings(self.settings("recipients: [ok@example.com, nope, 'two words@x.com', a@b]"))
        for bad in ("nope", "two words@x.com", "a@b"):
            self.assertIn(bad, str(cm.exception))
        self.assertNotIn("ok@example.com,", str(cm.exception))

    def test_addresses_that_try_to_inject_headers_are_rejected(self):
        for evil in ("a@example.com\nBcc: x@y.com", "a@example.com, b@example.com", "a@example.com;b@example.com",
                     "<a@example.com>", 'a"b@example.com'):
            with self.assertRaises(EmailError, msg=repr(evil)):
                emailer.load_settings(self.settings(f"recipients:\n  - {json.dumps(evil)}"))

    def test_a_display_name_cannot_contain_line_breaks(self):
        s = emailer.load_settings(self.settings('recipients:\n  - {address: a@example.com, name: "Bea\\nBcc: x@y.com"}'))
        self.assertNotIn("\n", s["recipients"][0]["name"])

    def test_options(self):
        s = emailer.load_settings(self.settings("enabled: false\nrecipients: [a@example.com]\nattach: [html, markdown]\n"
                                                "subject_prefix: Daily\ntopics_in_subject: 5"))
        self.assertEqual((s["enabled"], s["attach"], s["subject_prefix"], s["topics_in_subject"]),
                         (False, ["html", "markdown"], "Daily", 5))
        s = emailer.load_settings(self.settings("recipients: [a@example.com]\nattach: []"))
        self.assertEqual(s["attach"], [])

    def test_unknown_attachment_kinds_are_rejected(self):
        with self.assertRaises(EmailError) as cm:
            emailer.load_settings(self.settings("recipients: [a@example.com]\nattach: [pdf]"))
        self.assertIn("pdf", str(cm.exception))

    def test_a_missing_or_broken_file_has_a_helpful_message(self):
        with self.assertRaises(EmailError) as cm:
            emailer.load_settings(os.path.join(self.dir, "nope.yaml"))
        self.assertIn("not found", str(cm.exception))
        with self.assertRaises(EmailError) as cm:
            emailer.load_settings(self.settings("recipients: [unclosed"))
        self.assertIn("not valid YAML", str(cm.exception))

    def test_an_empty_file_gives_no_recipients_not_a_crash(self):
        self.assertEqual(emailer.load_settings(self.settings(""))["recipients"], [])


class SmtpSettingsTests(unittest.TestCase):
    def test_defaults_target_gmail_with_starttls(self):
        s = emailer.smtp_settings(dict(ENV))
        self.assertEqual((s["host"], s["port"], s["user"], s["sender"]), ("smtp.gmail.com", 587, "sender@gmail.com", "sender@gmail.com"))

    def test_everything_can_be_overridden(self):
        s = emailer.smtp_settings(dict(ENV, SMTP_HOST="smtp.example.com", SMTP_PORT="465", MAIL_FROM="news@example.com"))
        self.assertEqual((s["host"], s["port"], s["sender"]), ("smtp.example.com", 465, "news@example.com"))

    def test_empty_secrets_count_as_missing_and_the_message_explains_gmail_app_passwords(self):
        for env in ({}, {"SMTP_USERNAME": "", "SMTP_PASSWORD": ""}, {"SMTP_USERNAME": "x@gmail.com"}):
            with self.assertRaises(EmailError) as cm:
                emailer.smtp_settings(env)
            self.assertIn("app password", str(cm.exception))
        with self.assertRaises(EmailError) as cm:
            emailer.smtp_settings({"SMTP_PASSWORD": "x"})
        self.assertIn("SMTP_USERNAME", str(cm.exception))
        self.assertNotIn("SMTP_PASSWORD and", str(cm.exception))

    def test_blank_optional_values_fall_back_to_the_defaults(self):
        s = emailer.smtp_settings(dict(ENV, SMTP_HOST="", SMTP_PORT="", MAIL_FROM=""))
        self.assertEqual((s["host"], s["port"], s["sender"]), ("smtp.gmail.com", 587, "sender@gmail.com"))

    def test_a_non_numeric_port_is_rejected(self):
        with self.assertRaises(EmailError):
            emailer.smtp_settings(dict(ENV, SMTP_PORT="abc"))


class FindReportTests(FilesCase):
    def test_the_newest_report_is_found_with_its_sibling_files(self):
        self.report("2026-11-08")
        newest = self.report("2026-11-10")
        os.utime(newest + ".json", (9_000_000_000, 9_000_000_000))
        r = emailer.find_report(self.data)
        self.assertEqual((r["day"], r["json"]), ("2026-11-10", newest + ".json"))
        self.assertEqual((r["html"], r["md"], r["email_html"]), (newest + ".html", newest + ".md", newest + ".email.html"))

    def test_a_given_day_is_found_even_if_newer_reports_exist(self):
        old = self.report("2026-11-08")
        self.report("2026-11-10")
        self.assertEqual(emailer.find_report(self.data, "2026-11-08")["json"], old + ".json")

    def test_reports_named_with_a_subject_are_found_and_the_day_still_parsed(self):
        self.report("2026-11-10-irna-ir")
        self.assertEqual(emailer.find_report(self.data)["day"], "2026-11-10")

    def test_no_report_means_a_clear_error(self):
        with self.assertRaises(EmailError) as cm:
            emailer.find_report(self.data)
        self.assertIn("python run.py", str(cm.exception))
        self.report("2026-11-10")
        with self.assertRaises(EmailError) as cm:
            emailer.find_report(self.data, "2020-01-01")
        self.assertIn("2020-01-01", str(cm.exception))


class SubjectAndMessageTests(unittest.TestCase):
    def test_subject_lists_the_top_topics(self):
        results = [{"topic": t} for t in ("Midterms", "Krakow shooting", "Stephen Miller", "Fourth")]
        self.assertEqual(emailer.make_subject("HameNews", "2026-11-10", results, 3),
                         "HameNews 2026-11-10: Midterms, Krakow shooting, Stephen Miller")
        self.assertEqual(emailer.make_subject("HameNews", "2026-11-10", results, 1), "HameNews 2026-11-10: Midterms")

    def test_subject_without_topics_and_with_hostile_text(self):
        self.assertEqual(emailer.make_subject("HameNews", "2026-11-10", [], 3), "HameNews 2026-11-10")
        self.assertEqual(emailer.make_subject("X", "d", [{"topic": "a\nBcc: x@y.com"}], 3), "X d: a Bcc: x@y.com")
        long = emailer.make_subject("HameNews", "d", [{"topic": "x" * 500}] * 5, 5)
        self.assertLessEqual(len(long), 150)

    def test_the_message_has_plain_and_html_parts_attachments_and_clean_headers(self):
        rec = {"address": "reader@example.com", "name": "Reader Ö"}
        msg = emailer.build_message("news@example.com", rec, "Subject é\nBcc: x@y.com", "plain é", "<p>html é</p>",
                                    [("r.html", "<html>é</html>".encode("utf-8"), "text/html")])
        parsed = email.message_from_bytes(bytes(msg), policy=policy.default)
        self.assertEqual(parsed["From"], "news@example.com")
        self.assertIn("reader@example.com", parsed["To"])
        self.assertNotIn("\n", str(parsed["Subject"]))
        self.assertIn("Subject", parsed["Subject"])
        self.assertTrue(parsed["Message-ID"].endswith("@example.com>"))
        self.assertIsNone(parsed["Bcc"])
        self.assertEqual(parsed.get_body(("plain",)).get_content().strip(), "plain é")
        self.assertIn("html é", parsed.get_body(("html",)).get_content())
        attachment = next(parsed.iter_attachments())
        self.assertEqual((attachment.get_filename(), attachment.get_content_type()), ("r.html", "text/html"))


class SendReportTests(FilesCase):
    def setUp(self):
        super().setUp()
        self.settings("recipients: [a@example.com, 'b@example.com']\n")
        self.report()

    def send(self, environ=None, **kw):
        log = kw.pop("log", [])
        connect = kw.pop("connect", None) or fake_connect(log)
        summary = emailer.send_report(self.data, self.yaml, environ=dict(ENV) if environ is None else environ,
                                      connect=connect, **kw)
        return summary, log

    def test_each_recipient_gets_their_own_message(self):
        summary, log = self.send()
        sent = [x[1] for x in log if x[0] == "send"]
        self.assertEqual((summary["sent"], len(sent)), (2, 2))
        self.assertEqual([str(m["To"]) for m in sent], ["a@example.com", "b@example.com"])
        for m in sent:
            self.assertNotIn("b@example.com" if "a@example.com" in str(m["To"]) else "a@example.com", bytes(m).decode("utf-8", "ignore"))
            self.assertEqual(m["Subject"], "HameNews 2026-11-10: Midterms, Krakow shooting")
            self.assertEqual(m["From"], "sender@gmail.com")

    def test_connection_login_and_cleanup(self):
        _, log = self.send()
        self.assertEqual(log[0], ("connect", "smtp.gmail.com", 587, False))
        self.assertEqual(log[1], ("login", "sender@gmail.com", "abcd efgh ijkl mnop"))
        self.assertEqual(log[-1], ("quit",))

    def test_port_465_uses_implicit_ssl(self):
        _, log = self.send(environ=dict(ENV, SMTP_PORT="465"))
        self.assertEqual(log[0], ("connect", "smtp.gmail.com", 465, True))

    def test_the_email_body_comes_from_the_email_html_and_the_report_is_attached(self):
        _, log = self.send()
        msg = [x[1] for x in log if x[0] == "send"][0]
        self.assertIn("email body é", msg.get_body(("html",)).get_content())
        self.assertIn("plain text body é", msg.get_body(("plain",)).get_content())
        names = [a.get_filename() for a in msg.iter_attachments()]
        self.assertEqual(names, ["HameNews-2026-11-10.html"])
        self.assertIn("full report", next(msg.iter_attachments()).get_content())

    def test_attachments_follow_the_settings(self):
        self.settings("recipients: [a@example.com]\nattach: [html, markdown]")
        _, log = self.send()
        names = [a.get_filename() for a in [x[1] for x in log if x[0] == "send"][0].iter_attachments()]
        self.assertEqual(names, ["HameNews-2026-11-10.html", "HameNews-2026-11-10.md"])
        self.settings("recipients: [a@example.com]\nattach: []")
        _, log = self.send()
        self.assertEqual(list([x[1] for x in log if x[0] == "send"][0].iter_attachments()), [])

    def test_without_an_email_version_the_full_html_is_the_body(self):
        os.remove(os.path.join(self.data, "reports", "2026-11-10.email.html"))
        _, log = self.send()
        self.assertIn("full report", [x[1] for x in log if x[0] == "send"][0].get_body(("html",)).get_content())

    def test_an_incomplete_report_is_reported_not_crashed_on(self):
        os.remove(os.path.join(self.data, "reports", "2026-11-10.email.html"))
        os.remove(os.path.join(self.data, "reports", "2026-11-10.html"))
        with self.assertRaises(EmailError) as cm:
            self.send()
        self.assertIn("incomplete", str(cm.exception))

    def test_to_overrides_the_list_for_a_test_send(self):
        summary, log = self.send(to="me@example.com")
        self.assertEqual(summary["recipients"], ["me@example.com"])
        self.assertEqual(len([x for x in log if x[0] == "send"]), 1)
        with self.assertRaises(EmailError):
            self.send(to="not an address")

    def test_switched_off_sends_nothing_but_a_test_send_still_works(self):
        self.settings("enabled: false\nrecipients: [a@example.com]")
        summary, log = self.send()
        self.assertEqual((summary["sent"], log), (0, []))
        self.assertIn("switched off", summary["skipped"])
        self.assertEqual(self.send(to="me@example.com")[0]["sent"], 1)

    def test_no_recipients_is_an_error(self):
        self.settings("recipients: []")
        with self.assertRaises(EmailError) as cm:
            self.send()
        self.assertIn("No recipients", str(cm.exception))

    def test_missing_credentials_are_reported_before_any_connection(self):
        log = []
        with self.assertRaises(EmailError):
            emailer.send_report(self.data, self.yaml, environ={}, connect=fake_connect(log))
        self.assertEqual(log, [])

    def test_a_rejected_login_explains_app_passwords_and_never_shows_the_password(self):
        err = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
        with self.assertRaises(EmailError) as cm:
            self.send(connect=fake_connect([], fail_login=err))
        self.assertIn("APP PASSWORD", str(cm.exception))
        self.assertNotIn("abcd efgh", str(cm.exception))

    def test_network_and_server_errors_become_readable_errors(self):
        for failure in (OSError("Network is unreachable"), smtplib.SMTPServerDisconnected("gone")):
            with self.assertRaises(EmailError) as cm:
                self.send(connect=fake_connect([], fail_connect=failure))
            self.assertIn("smtp.gmail.com:587", str(cm.exception))
        with self.assertRaises(EmailError):
            self.send(connect=fake_connect([], fail_send=smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"no")})))

    def test_the_password_is_never_in_the_summary_or_the_log_output(self):
        with self.assertLogs("trendwatch", level="INFO") as logs:
            summary, _ = self.send()
        self.assertNotIn("abcd efgh", json.dumps(summary))
        self.assertNotIn("abcd efgh", " ".join(logs.output))


class DefaultConnectTests(unittest.TestCase):
    def test_port_587_connects_in_the_clear_and_upgrades_with_starttls(self):
        calls = []

        class Server:
            def __init__(self, host, port, timeout=None):
                calls.append(("SMTP", host, port, timeout))

            def ehlo(self):
                calls.append("ehlo")

            def starttls(self, context=None):
                calls.append(("starttls", context is not None and context.check_hostname))

        with unittest.mock.patch.object(smtplib, "SMTP", Server):
            server = emailer.default_connect("smtp.gmail.com", 587, False)
        self.assertIsInstance(server, Server)
        self.assertEqual(calls, [("SMTP", "smtp.gmail.com", 587, 30), "ehlo", ("starttls", True), "ehlo"])

    def test_port_465_uses_ssl_from_the_start_with_certificate_checking(self):
        seen = {}

        class SslServer:
            def __init__(self, host, port, timeout=None, context=None):
                seen.update(host=host, port=port, timeout=timeout, verifies=context.check_hostname)

        with unittest.mock.patch.object(smtplib, "SMTP_SSL", SslServer):
            emailer.default_connect("smtp.example.com", 465, True)
        self.assertEqual(seen, {"host": "smtp.example.com", "port": 465, "timeout": 30, "verifies": True})


class DryRunTests(FilesCase):
    def setUp(self):
        super().setUp()
        self.settings("recipients: [a@example.com]\n")
        self.report()

    def test_a_dry_run_needs_no_credentials_and_sends_nothing(self):
        log = []
        summary = emailer.send_report(self.data, self.yaml, environ={}, dry_run=True, connect=fake_connect(log))
        self.assertEqual(log, [])
        self.assertTrue(summary["dry_run"])
        self.assertEqual((summary["subject"], summary["recipients"], summary["attachments"]),
                         ("HameNews 2026-11-10: Midterms, Krakow shooting", ["a@example.com"], ["HameNews-2026-11-10.html"]))

    def test_it_saves_a_preview_page_and_the_raw_message(self):
        summary = emailer.send_report(self.data, self.yaml, environ={}, dry_run=True)
        self.assertIn("email body", open(summary["preview"], encoding="utf-8").read())
        raw = open(os.path.join(self.data, "email-preview.eml"), "rb").read()
        self.assertIn(b"Subject: HameNews 2026-11-10", raw)


if __name__ == "__main__":
    unittest.main()
