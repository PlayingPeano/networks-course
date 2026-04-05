#!/usr/bin/env python3
import argparse
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

HOST, PORT = "smtp.mail.ru", 465


def main() -> None:
    p = argparse.ArgumentParser(description="Mail.ru SMTP")
    p.add_argument("--to", required=True, help="reciever")
    p.add_argument("--format", choices=("txt", "html"), default="txt")
    p.add_argument("--subject", default="Lab 5 — test message")
    p.add_argument("--from", dest="sender", default="", help="sender (else MAIL_FROM / SMTP_USER)")
    p.add_argument("--body-file", default="", help="file; else stdin; else default")
    a = p.parse_args()

    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = a.sender.strip() or os.environ.get("MAIL_FROM", "") or user
    if not user or not password:
        sys.exit("set SMTP_USER and SMTP_PASSWORD (@mail.ru and password)")
    if not sender:
        sys.exit("set --from or MAIL_FROM")

    if a.body_file:
        with open(a.body_file, encoding="utf-8") as f:
            body = f.read()
    elif not sys.stdin.isatty():
        body = sys.stdin.read()
    elif a.format == "html":
        body = "<p>Hi! It's an <b>HTML</b> from lab5.</p>"
    else:
        body = "Hi!\n\nIt's a txt from lab5.\n"

    sub = "html" if a.format == "html" else "plain"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, a.to, a.subject
    msg.set_content(body, subtype=sub, charset="utf-8")

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(HOST, PORT, timeout=30, context=ctx) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        sys.exit(f"sending: {e}")
    print("message sent", file=sys.stderr)


if __name__ == "__main__":
    main()
