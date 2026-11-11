#!/usr/bin/env python3
"""Email the newest HameNews report to the people listed in emails.yaml.

  python send_report.py --dry-run                 # build the email, save a preview, send nothing
  python send_report.py --to you@example.com      # send only to this address (a test)
  python send_report.py                           # send to everyone in emails.yaml

Credentials come from environment variables: SMTP_USERNAME and SMTP_PASSWORD (required), and optionally
SMTP_HOST (default smtp.gmail.com), SMTP_PORT (default 587) and MAIL_FROM (default: the username).
"""
import argparse
import logging
import sys

from trendwatch.emailer import EmailError, send_report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Email the newest HameNews report.")
    ap.add_argument("--recipients", default="emails.yaml", help="the recipients file (default emails.yaml)")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--date", help="send the report for this date (YYYY-MM-DD) instead of the newest")
    ap.add_argument("--to", help="send only to this address, ignoring emails.yaml (for testing)")
    ap.add_argument("--dry-run", action="store_true", help="build the email and save a preview; send nothing")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        summary = send_report(args.data_dir, args.recipients, day=args.date, to=args.to, dry_run=args.dry_run)
    except EmailError as e:
        sys.exit(f"Error: {e}")
    if summary.get("skipped"):
        print(summary["skipped"])
    elif summary.get("dry_run"):
        print(f"Dry run: nothing was sent.\nSubject:     {summary['subject']}\n"
              f"Recipients:  {', '.join(summary['recipients'])}\nAttachments: {', '.join(summary['attachments']) or 'none'}\n"
              f"Preview:     {summary['preview']}  (open it in a browser)")
    else:
        print(f"Sent to {summary['sent']} recipient(s): {', '.join(summary['recipients'])}\nSubject: {summary['subject']}")


if __name__ == "__main__":
    main()
