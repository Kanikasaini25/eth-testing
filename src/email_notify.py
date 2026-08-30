from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText

from src.config import get_env, get_env_bool


@dataclass
class EmailResult:
    success: bool
    message: str = ""


def notify_recipients() -> list[str]:
    raw = get_env("NOTIFY_EMAIL")
    return [part.strip() for part in raw.replace(";", ",").split(",") if "@" in part]


def is_email_configured() -> bool:
    if not get_env_bool("EMAIL_NOTIFY_ENABLED", True):
        return False
    required = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")
    return all(get_env(name) for name in required) and bool(notify_recipients())


def send_email(subject: str, body: str) -> EmailResult:
    if not is_email_configured():
        return EmailResult(success=False, message="Email not configured in .env")

    host = get_env("SMTP_HOST")
    port = int(get_env("SMTP_PORT", "587"))
    user = get_env("SMTP_USER")
    password = get_env("SMTP_PASSWORD")
    from_addr = get_env("SMTP_FROM") or user
    to_addrs = notify_recipients()
    use_tls = get_env_bool("SMTP_USE_TLS", True)

    message = MIMEText(body, "plain")
    message["From"] = from_addr
    message["To"] = ", ".join(to_addrs)
    message["Subject"] = subject

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if use_tls:
                server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, to_addrs, message.as_string())
        return EmailResult(success=True, message=f"Email sent to {len(to_addrs)} recipient(s)")
    except Exception as exc:
        return EmailResult(success=False, message=str(exc))


def notify_event(subject: str, lines: list[str]) -> EmailResult:
    return send_email(subject, "\n".join(lines))


def send_test_email() -> EmailResult:
    recipients = notify_recipients()
    return notify_event(
        "ETHUSD 100-lot strategies — test email",
        [
            "This is a test from the ETHUSD live runner.",
            f"Recipients configured: {len(recipients)}",
            "You will get mail on range/trend/funding entries, fills, and closes.",
        ],
    )
