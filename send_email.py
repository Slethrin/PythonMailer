"""
Email Sender with PDF Attachment Support
Uses Gmail SMTP with an App Password (NOT your regular Gmail password).

Setup:
  1. Go to https://myaccount.google.com/apppasswords
  2. Generate an App Password for "Mail"
  3. Set environment variables:
       export EMAIL_ADDRESS="suryanshbaranwal53@gmail.com"
       export EMAIL_APP_PASSWORD="your_16_char_app_password"

Usage:
  python send_email.py \
    --to "recipient@example.com" \
    --subject "Your Subject" \
    --body "Your email body text." \
    --attach "/path/to/file.pdf"
"""

import smtplib
import os
import argparse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path


def send_email(
    to_address: str,
    subject: str,
    body: str,
    attachments: list[str] = None,
    html: bool = False,
):
    # --- Credentials from environment variables (NEVER hardcode these) ---
    from_address = os.environ.get("EMAIL_ADDRESS")
    app_password = os.environ.get("EMAIL_APP_PASSWORD")

    if not from_address or not app_password:
        raise EnvironmentError(
            "Missing credentials. Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD "
            "as environment variables.\n"
            "Get an App Password at: https://myaccount.google.com/apppasswords"
        )

    # --- Build the email ---
    msg = MIMEMultipart()
    msg["From"] = from_address
    msg["To"] = to_address
    msg["Subject"] = subject

    # Attach body (plain text or HTML)
    mime_type = "html" if html else "plain"
    msg.attach(MIMEText(body, mime_type))

    # --- Attach files ---
    for filepath in (attachments or []):
        path = Path(filepath)
        if not path.exists():
            print(f"  [WARNING] File not found, skipping: {filepath}")
            continue

        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())

        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{path.name}"',
        )
        msg.attach(part)
        print(f"  [OK] Attached: {path.name}")

    # --- Send via Gmail SMTP ---
    print(f"Connecting to Gmail SMTP...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_address, app_password)
        server.sendmail(from_address, to_address, msg.as_string())

    print(f"Email sent successfully to {to_address}")


def main():
    parser = argparse.ArgumentParser(description="Send an email with optional attachments.")
    parser.add_argument("--to",      required=True,  help="Recipient email address")
    parser.add_argument("--subject", required=True,  help="Email subject line")
    parser.add_argument("--body",    required=True,  help="Email body text (or HTML if --html)")
    parser.add_argument("--attach",  nargs="*",      help="Path(s) to file(s) to attach", default=[])
    parser.add_argument("--html",    action="store_true", help="Treat body as HTML")

    args = parser.parse_args()

    send_email(
        to_address=args.to,
        subject=args.subject,
        body=args.body,
        attachments=args.attach,
        html=args.html,
    )


if __name__ == "__main__":
    main()
