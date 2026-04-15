"""
Send trade plan email via Gmail SMTP.
Reads credentials from environment variables set in .alpha_engine.env
"""
from __future__ import annotations

import argparse
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def get_env(*names: str, default: str | None = None) -> str | None:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


def send_plan_email(txt_path: Path, csv_path: Path) -> None:
    # Support both old and new env var names
    smtp_user = get_env("SMTP_USER", "AE_SMTP_USER")
    smtp_pass = get_env("SMTP_PASS", "AE_SMTP_PASS")
    smtp_host = get_env("SMTP_HOST", "AE_SMTP_HOST", default="smtp.gmail.com")
    smtp_port = int(get_env("SMTP_PORT", "AE_SMTP_PORT", default="587") or "587")
    mail_to   = get_env("EMAIL_TO", "SMTP_TO", "AE_EMAIL_TO")
    mail_from = get_env("EMAIL_FROM", "SMTP_FROM", "AE_EMAIL_FROM", default=smtp_user or "")

    missing = []
    if not smtp_user: missing.append("SMTP_USER")
    if not smtp_pass: missing.append("SMTP_PASS")
    if not mail_to:   missing.append("EMAIL_TO")
    if missing:
        raise ValueError(f"Missing env vars: {', '.join(missing)}")

    msg = EmailMessage()
    msg["Subject"] = f"Alpha Engine — Trade Plan {txt_path.stem.replace('trade_plan_', '')}"
    msg["From"] = mail_from
    msg["To"] = mail_to

    body = txt_path.read_text(encoding="utf-8", errors="replace")
    msg.set_content(body)

    msg.add_attachment(
        csv_path.read_bytes(),
        maintype="text",
        subtype="csv",
        filename=csv_path.name,
    )

    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.ehlo()
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)

    print(f"Email sent to {mail_to}: {txt_path.name} + {csv_path.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--txt", required=True)
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()
    send_plan_email(Path(args.txt), Path(args.csv))


if __name__ == "__main__":
    main()
