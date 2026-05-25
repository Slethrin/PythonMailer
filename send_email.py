"""
email_cron.py — Redis-driven Email Cron Job
============================================
Runs every 30 minutes (via system cron or --loop mode).
Reads email jobs from a Redis hash map, sends unsent ones,
and marks each as sent back in Redis.

Redis Hash Structure expected (one hash per email job):
  Key  : emails:<id>          e.g. emails:1, emails:abc123
  Fields:
    to        → recipient email address         (required)
    subject   → email subject                   (required)
    body      → email body text or HTML         (required)
    is_sent   → "0" (pending) | "1" (sent)      (required, updated by script)
    html      → "1" for HTML body, "0" default  (optional)
    attach    → comma-separated file paths      (optional)

Credentials (set as env vars — NEVER hardcode):
  EMAIL_ADDRESS       your Gmail address
  EMAIL_APP_PASSWORD  Gmail App Password (not your login password)
                      → https://myaccount.google.com/apppasswords

Usage:
  # Run once (for cron):
  python3 email_cron.py

  # Run in loop mode (every 30 min, no cron needed):
  python3 email_cron.py --loop

Cron setup (runs every 30 minutes):
  crontab -e
  */30 * * * * EMAIL_ADDRESS=suryanshbaranwal53@gmail.com EMAIL_APP_PASSWORD=<app_pw> /usr/bin/python3 /path/to/email_cron.py >> /var/log/email_cron.log 2>&1
"""

import os
import time
import smtplib
import logging
import argparse
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import redis

# ─── Config ────────────────────────────────────────────────────────────────────

REDIS_URL   = "redis://default:nEIPnMeh2ZoJQyljeilTJuftFgtBGoRT@redis-13795.crce295.us-east-1-1.ec2.cloud.redislabs.com:13795"
HASH_PREFIX = "emails:"          # Script scans all keys matching "emails:*"
POLL_EVERY  = 30 * 60            # seconds (30 minutes) — used in --loop mode

GMAIL_HOST  = "smtp.gmail.com"
GMAIL_PORT  = 465                # SSL port

# ─── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("email_cron")

# ─── Redis ─────────────────────────────────────────────────────────────────────

def get_redis() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=10)


def fetch_pending_jobs(r: redis.Redis) -> list[dict]:
    """Return all email hashes where is_sent != '1'."""
    pending = []
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=f"{HASH_PREFIX}*", count=100)
        for key in keys:
            job = r.hgetall(key)
            if not job:
                continue
            if job.get("is_sent", "0") != "1":
                job["_key"] = key
                pending.append(job)
        if cursor == 0:
            break
    return pending


def mark_sent(r: redis.Redis, key: str):
    r.hset(key, "is_sent", "1")

# ─── Email ─────────────────────────────────────────────────────────────────────

def send_email(job: dict, from_address: str, app_password: str) -> bool:
    to      = job.get("to", "").strip()
    subject = job.get("subject", "(no subject)").strip()
    body    = job.get("body", "").strip()
    is_html = job.get("html", "0") == "1"
    attach_raw = job.get("attach", "")
    attachments = [p.strip() for p in attach_raw.split(",") if p.strip()]

    if not to:
        log.warning("Job %s has no 'to' field — skipping.", job["_key"])
        return False

    msg = MIMEMultipart()
    msg["From"]    = from_address
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if is_html else "plain"))

    for filepath in attachments:
        path = Path(filepath)
        if not path.exists():
            log.warning("  Attachment not found, skipping: %s", filepath)
            continue
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{path.name}"')
        msg.attach(part)
        log.info("  Attached: %s", path.name)

    try:
        with smtplib.SMTP_SSL(GMAIL_HOST, GMAIL_PORT) as server:
            server.login(from_address, app_password)
            server.sendmail(from_address, to, msg.as_string())
        log.info("  ✓ Sent → %s | subject: %s", to, subject)
        return True
    except smtplib.SMTPException as e:
        log.error("  ✗ SMTP error for %s: %s", job["_key"], e)
        return False

# ─── Main loop ─────────────────────────────────────────────────────────────────

def run_once():
    from_address = os.environ.get("EMAIL_ADDRESS")
    app_password = os.environ.get("EMAIL_APP_PASSWORD")

    if not from_address or not app_password:
        raise EnvironmentError(
            "Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD environment variables.\n"
            "Get an App Password: https://myaccount.google.com/apppasswords"
        )

    log.info("── Cron tick started ──────────────────────────────")

    try:
        r = get_redis()
        r.ping()
        log.info("Redis connected OK.")
    except Exception as e:
        log.error("Cannot connect to Redis: %s", e)
        return

    pending = fetch_pending_jobs(r)
    log.info("Found %d pending email(s).", len(pending))

    sent_count = 0
    for job in pending:
        log.info("Processing job: %s → %s", job["_key"], job.get("to"))
        if send_email(job, from_address, app_password):
            mark_sent(r, job["_key"])
            sent_count += 1

    log.info("Done. Sent %d/%d email(s).", sent_count, len(pending))
    log.info("── Cron tick finished ─────────────────────────────")


def run_loop():
    log.info("Starting in loop mode — polling every %d minutes.", POLL_EVERY // 60)
    while True:
        run_once()
        log.info("Sleeping %d minutes until next poll...", POLL_EVERY // 60)
        time.sleep(POLL_EVERY)


# ─── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Redis-driven email cron job.")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously every 30 min instead of once (no system cron needed).",
    )
    args = parser.parse_args()

    if args.loop:
        run_loop()
    else:
        run_once()
