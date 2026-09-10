from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.config import get_env


@dataclass
class EmailResult:
    success: bool
    message: str = ""


def is_email_enabled() -> bool:
    enabled = get_env("EMAIL_NOTIFY_ENABLED", "false").lower()
    return enabled in {"1", "true", "yes", "on"}


def is_email_configured() -> bool:
    if not is_email_enabled():
        return False
    required = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "NOTIFY_EMAIL")
    return all(get_env(name) for name in required)


def _smtp_settings() -> dict[str, str | int]:
    return {
        "host": get_env("SMTP_HOST"),
        "port": int(get_env("SMTP_PORT", "587")),
        "user": get_env("SMTP_USER"),
        "password": get_env("SMTP_PASSWORD"),
        "from_addr": get_env("SMTP_FROM") or get_env("SMTP_USER"),
        "to_addr": get_env("NOTIFY_EMAIL"),
        "use_tls": get_env("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"},
    }


def send_email(subject: str, body: str) -> EmailResult:
    if not is_email_configured():
        return EmailResult(
            success=False,
            message="Email notifications disabled or SMTP settings missing in .env",
        )

    settings = _smtp_settings()
    host = str(settings["host"])
    port = int(settings["port"])
    user = str(settings["user"])
    password = str(settings["password"])
    from_addr = str(settings["from_addr"])
    to_addr = str(settings["to_addr"])
    use_tls = bool(settings["use_tls"])

    message = MIMEMultipart()
    message["From"] = from_addr
    message["To"] = to_addr
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if use_tls:
                server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, [to_addr], message.as_string())
        return EmailResult(success=True, message=f"Email sent to {to_addr}")
    except Exception as exc:  # noqa: BLE001
        return EmailResult(success=False, message=str(exc))


def send_entry_signal_email(
    *,
    symbol: str,
    side: str,
    entry_price: float,
    stop_loss: float,
    target: float,
    entry_lots: int,
    entry_ts: str,
    buy_volume: float,
    sell_volume: float,
    pullback_high: float,
    pullback_low: float,
) -> EmailResult:
    trade_label = "BUY (LONG)" if side == "long" else "SELL (SHORT)"
    subject = f"ETH Volume Bias Entry: {trade_label} {symbol} @ {entry_price:.2f}"
    body = "\n".join(
        [
            "ETH India volume-bias strategy — Entry",
            "",
            f"Symbol:         {symbol}",
            f"Signal:         {trade_label}",
            f"Entry time:     {entry_ts}",
            f"Entry price:    {entry_price:.2f}",
            f"Stop (wick):    {stop_loss:.2f}",
            f"Target:         {target:.2f} (+5% full close)",
            f"Trail:          +1% keep wick SL; +2%→+1%; +3%→+2%; +4%→+3%",
            f"Size:           {entry_lots} lots",
            f"Buy volume:     {buy_volume:.4f}",
            f"Sell volume:    {sell_volume:.4f}",
            f"Pullback high:  {pullback_high:.2f}",
            f"Pullback low:   {pullback_low:.2f}",
            "",
            "Order placed on Delta Exchange.",
        ]
    )
    return send_email(subject, body)


def send_stop_loss_email(
    *,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    lots: int,
    stop_loss: float,
    exit_type: str = "stop_loss",
) -> EmailResult:
    trade_label = "LONG" if side == "long" else "SHORT"
    points = (exit_price - entry_price) if side == "long" else (entry_price - exit_price)
    headline = "Stop Loss Hit (Exchange)" if exit_type == "exchange_stop" else "Stop Loss Hit"
    subject = f"ETH Volume Bias {headline}: {lots} lots {symbol} @ {exit_price:.2f}"
    body = "\n".join(
        [
            f"ETH India volume-bias strategy — {headline}",
            "",
            f"Symbol:      {symbol}",
            f"Side:        {trade_label}",
            f"Entry:       {entry_price:.2f}",
            f"Stop:        {stop_loss:.2f}",
            f"Exit:        {exit_price:.2f}",
            f"Lots:        {lots}",
            f"Points:      {points:.2f}",
        ]
    )
    return send_email(subject, body)


def send_take_profit_email(
    *,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    lots: int,
    target: float,
) -> EmailResult:
    trade_label = "LONG" if side == "long" else "SHORT"
    points = (exit_price - entry_price) if side == "long" else (entry_price - exit_price)
    subject = f"ETH Volume Bias Take Profit: {lots} lots {symbol} @ {exit_price:.2f}"
    body = "\n".join(
        [
            "ETH India volume-bias strategy — Take Profit (+5% full close)",
            "",
            f"Symbol:      {symbol}",
            f"Side:        {trade_label}",
            f"Entry:       {entry_price:.2f}",
            f"Target:      {target:.2f}",
            f"Exit:        {exit_price:.2f}",
            f"Lots:        {lots}",
            f"Points:      {points:.2f}",
        ]
    )
    return send_email(subject, body)


def send_test_email() -> EmailResult:
    return send_email(
        subject="ETH Volume Bias Strategy — Test Email",
        body="This is a test email from the ETH India volume-bias live alerts.",
    )
