"""Email the daily report.

Standard library only (smtplib), so there is nothing extra to install and no third-party action ever
sees the credentials. Recipients come from emails.yaml; SMTP credentials come from environment variables
(GitHub secrets in the workflow). Each recipient gets their own message, so addresses are never shared.
"""
import glob
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import yaml

from .util import log

ADDRESS = re.compile(r"^[^@\s,;<>()\[\]\"']+@[^@\s,;<>()\[\]\"']+\.[^@\s,;<>()\[\]\"']{2,}$")
DEFAULTS = {"enabled": True, "subject_prefix": "HameNews", "topics_in_subject": 3, "attach": ["html"]}
ATTACHMENTS = {"html": ("text/html", ".html"), "markdown": ("text/markdown", ".md")}


class EmailError(Exception):
    """A problem the user can fix; the message says how."""


# ----------------------------------------------------------------------- settings
def load_settings(path):
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise EmailError(f"{path} not found. It lists who receives the report (see the README).")
    except yaml.YAMLError as e:
        raise EmailError(f"{path} is not valid YAML: {e}")
    settings = {**DEFAULTS, **{k: v for k, v in raw.items() if k != "recipients"}}

    recipients, bad, seen = [], [], set()
    for entry in raw.get("recipients") or []:
        address = str(entry.get("address", "") if isinstance(entry, dict) else entry or "").strip()
        name = str(entry.get("name", "") if isinstance(entry, dict) else "").strip()
        if not address:
            continue
        if not ADDRESS.match(address):
            bad.append(address)
        elif address.lower() not in seen:
            seen.add(address.lower())
            recipients.append({"address": address, "name": re.sub(r"[\r\n]+", " ", name)})
    if bad:
        raise EmailError(f"These recipients in {path} do not look like email addresses: {', '.join(bad)}")

    attach = settings["attach"] or []
    unknown = [a for a in attach if a not in ATTACHMENTS]
    if unknown:
        raise EmailError(f"Unknown attach value(s) in {path}: {', '.join(map(str, unknown))} (use html and/or markdown)")
    settings["attach"], settings["recipients"] = list(attach), recipients
    return settings


def smtp_settings(environ=None):
    """SMTP login details from the environment; raises with exact instructions when something is missing."""
    environ = os.environ if environ is None else environ
    user = environ.get("SMTP_USERNAME") or ""
    password = environ.get("SMTP_PASSWORD") or ""
    missing = [n for n, v in (("SMTP_USERNAME", user), ("SMTP_PASSWORD", password)) if not v]
    if missing:
        raise EmailError(
            f"Missing {' and '.join(missing)}. Add them as secrets (GitHub: Settings > Secrets and variables > "
            "Actions) or environment variables. For Gmail: SMTP_USERNAME is your full Gmail address and "
            "SMTP_PASSWORD is a 16-character app password (Google Account > Security > 2-Step Verification > App passwords).")
    port_text = environ.get("SMTP_PORT") or "587"
    if not port_text.isdigit():
        raise EmailError(f"SMTP_PORT must be a number (587 or 465), not {port_text!r}.")
    return {"host": environ.get("SMTP_HOST") or "smtp.gmail.com", "port": int(port_text), "user": user,
            "password": password, "sender": environ.get("MAIL_FROM") or user}


# ----------------------------------------------------------------------- the report to send
def find_report(data_dir, day=None):
    """The newest report (or the newest for `day`): its date and the files belonging to it."""
    pattern = os.path.join(data_dir, "reports", (f"{day}*" if day else "*") + ".json")
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    if not files:
        raise EmailError(f"No report found in {os.path.join(data_dir, 'reports')}"
                         + (f" for {day}" if day else "") + ". Run `python run.py` first.")
    stem = files[-1][:-len(".json")]
    return {"stem": stem, "day": re.match(r"\d{4}-\d{2}-\d{2}", os.path.basename(stem)).group(0)
            if re.match(r"\d{4}-\d{2}-\d{2}", os.path.basename(stem)) else (day or ""),
            "json": files[-1], "html": stem + ".html", "md": stem + ".md", "email_html": stem + ".email.html"}


def make_subject(prefix, day, results, how_many=3):
    titles = [re.sub(r"\s+", " ", str(r.get("topic", ""))).strip()[:60] for r in results][:max(how_many, 0)]
    subject = f"{prefix} {day}".strip() + (": " + ", ".join(t for t in titles if t) if any(titles) else "")
    return subject[:150]


def build_message(sender, recipient, subject, text, html, attachments=()):
    msg = EmailMessage()
    msg["Subject"] = re.sub(r"[\r\n]+", " ", subject)
    msg["From"] = sender
    msg["To"] = formataddr((recipient.get("name", ""), recipient["address"]))
    msg["Date"] = formatdate()
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    for filename, data, mime in attachments:
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg


def _read(path, binary=False):
    with open(path, "rb" if binary else "r", **({} if binary else {"encoding": "utf-8"})) as f:
        return f.read()


def default_connect(host, port, use_ssl):
    context = ssl.create_default_context()
    if use_ssl:
        return smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    server = smtplib.SMTP(host, port, timeout=30)
    server.ehlo()
    server.starttls(context=context)
    server.ehlo()
    return server


def deliver(messages, smtp, connect=None):
    connect = connect or default_connect
    try:
        server = connect(smtp["host"], smtp["port"], smtp["port"] == 465)
        server.login(smtp["user"], smtp["password"])
        for message in messages:
            server.send_message(message)
        server.quit()
    except smtplib.SMTPAuthenticationError:
        raise EmailError("The mail server rejected the login. For Gmail use the full address as SMTP_USERNAME and a "
                         "16-character APP PASSWORD (not your normal password) as SMTP_PASSWORD; 2-Step Verification "
                         "must be on for Google to offer app passwords.") from None
    except (smtplib.SMTPException, OSError) as e:
        raise EmailError(f"Could not send the email via {smtp['host']}:{smtp['port']}: {type(e).__name__}: {e}") from None


def send_report(data_dir, settings_path, environ=None, day=None, to=None, dry_run=False, connect=None):
    """Email the newest report to everyone in emails.yaml (or just `to`). Returns a summary dict."""
    settings = load_settings(settings_path)
    if not settings["enabled"] and not to:
        return {"sent": 0, "skipped": f"emails are switched off in {settings_path} (enabled: false)"}
    recipients = [{"address": to, "name": ""}] if to else settings["recipients"]
    if to and not ADDRESS.match(to):
        raise EmailError(f"{to!r} does not look like an email address.")
    if not recipients:
        raise EmailError(f"No recipients in {settings_path}. Add at least one address under 'recipients'.")

    report = find_report(data_dir, day)
    results = json.loads(_read(report["json"])) if os.path.exists(report["json"]) else []
    text = _read(report["md"]) if os.path.exists(report["md"]) else "Open the attached report."
    html_path = report["email_html"] if os.path.exists(report["email_html"]) else report["html"]
    if not os.path.exists(html_path):
        raise EmailError(f"The report files for {report['day']} are incomplete (no HTML found next to {report['json']}).")
    html = _read(html_path)
    subject = make_subject(settings["subject_prefix"], report["day"], results, settings["topics_in_subject"])

    attachments = []
    for kind in settings["attach"]:
        mime, ext = ATTACHMENTS[kind]
        source = report["html"] if kind == "html" else report["md"]
        if os.path.exists(source):
            attachments.append((f"HameNews-{report['day']}{ext}", _read(source, binary=True), mime))

    if dry_run:     # no credentials needed: build the message and save a preview you can open
        sender = (environ if environ is not None else os.environ).get("MAIL_FROM") or "hamenews@example.invalid"
        message = build_message(sender, recipients[0], subject, text, html, attachments)
        os.makedirs(data_dir, exist_ok=True)
        preview = os.path.join(data_dir, "email-preview.html")
        with open(preview, "w", encoding="utf-8") as f:
            f.write(html)
        with open(os.path.join(data_dir, "email-preview.eml"), "wb") as f:
            f.write(bytes(message))
        return {"sent": 0, "dry_run": True, "subject": subject, "recipients": [r["address"] for r in recipients],
                "attachments": [a[0] for a in attachments], "preview": preview, "report": report["stem"]}

    smtp = smtp_settings(environ)
    messages = [build_message(smtp["sender"], r, subject, text, html, attachments) for r in recipients]
    deliver(messages, smtp, connect)
    log.info("emailed %d recipient(s): %s", len(messages), subject)
    return {"sent": len(messages), "subject": subject, "recipients": [r["address"] for r in recipients],
            "attachments": [a[0] for a in attachments], "report": report["stem"]}
