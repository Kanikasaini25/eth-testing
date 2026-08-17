#!/usr/bin/env python3
"""Send a test email using SMTP settings from .env."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.email_notify import is_email_configured, send_test_email


def main() -> int:
    if not is_email_configured():
        print("Email not configured. Set EMAIL_NOTIFY_ENABLED=true and SMTP_* in .env")
        return 1

    result = send_test_email()
    if result.success:
        print(result.message)
        return 0
    print(f"FAILED: {result.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
