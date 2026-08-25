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
    target_1: float,
    target_2: float,
    entry_lots: int,
    partial_lots: int,
    runner_lots: int,
    entry_line: str,
    entry_ts: str,
    upper_level: float | None = None,
    lower_level: float | None = None,
    strategy_name: str = "LQDTY Liquidity Strategy",
) -> EmailResult:
    trade_label = "BUY (LONG)" if side == "long" else "SELL (SHORT)"
    subject = f"{strategy_name} Entry: {trade_label} {symbol} @ {entry_price:.2f}"

    body = "\n".join(
        [
            f"{strategy_name} — Entry Signal",
            "",
            f"Symbol:      {symbol}",
            f"Signal:      {trade_label}",
            f"Entry time:  {entry_ts}",
            f"Entry price: {entry_price:.2f}",
            f"Stop loss:   {stop_loss:.2f}",
            f"Target 1:    {target_1:.2f} (partial {partial_lots} lots @ +5 pts)",
            f"Target 2:    {target_2:.2f} (runner {runner_lots} lots swing target)",
            f"Size:        {entry_lots} lots",
            f"Liquidity:   {entry_line} line",
            "",
            f"Upper line:  {upper_level if upper_level is not None else '—'}",
            f"Lower line:  {lower_level if lower_level is not None else '—'}",
            "",
            "Order placed on Delta Exchange demo/live account.",
        ]
    )
    return send_email(subject, body)


def send_partial_exit_email(
    *,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    partial_lots: int,
    runner_lots: int,
    runner_stop_loss: float,
    target_1: float,
) -> EmailResult:
    trade_label = "LONG" if side == "long" else "SHORT"
    points = (exit_price - entry_price) if side == "long" else (entry_price - exit_price)
    subject = f"LQDTY Partial Exit: {partial_lots} lots {symbol} @ {exit_price:.2f} (+{points:.2f} pts)"

    body = "\n".join(
        [
            "LQDTY Liquidity Strategy — Partial Exit",
            "",
            f"Symbol:         {symbol}",
            f"Side:           {trade_label}",
            f"Entry price:    {entry_price:.2f}",
            f"Partial exit:   {partial_lots} lots @ {exit_price:.2f}",
            f"Points gained:  {points:.2f}",
            f"Target 1:       {target_1:.2f}",
            f"Runner left:    {runner_lots} lots",
            f"Runner SL:      {runner_stop_loss:.2f}",
            "",
            "80 lots booked. 20-lot runner continues with trailing stop.",
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
    partial_was_taken: bool = False,
    strategy_name: str = "LQDTY Liquidity Strategy",
) -> EmailResult:
    trade_label = "LONG" if side == "long" else "SHORT"
    points = (exit_price - entry_price) if side == "long" else (entry_price - exit_price)
    label_map = {
        "stop_loss": "Stop Loss Hit",
        "trailing_stop": "Trailing Stop Hit",
        "breakeven_stop": "Breakeven Stop Hit",
        "exchange_stop": "Stop Loss Hit (Exchange)",
    }
    headline = label_map.get(exit_type, "Stop Loss Hit")
    subject = f"{strategy_name} {headline}: {lots} lots {symbol} @ {exit_price:.2f}"

    body = "\n".join(
        [
            f"{strategy_name} — {headline}",
            "",
            f"Symbol:         {symbol}",
            f"Side:           {trade_label}",
            f"Entry price:    {entry_price:.2f}",
            f"Stop loss:      {stop_loss:.2f}",
            f"Exit price:     {exit_price:.2f}",
            f"Lots closed:    {lots}",
            f"Points:         {points:.2f}",
            f"Partial before: {'Yes' if partial_was_taken else 'No'}",
            "",
            "Position closed on Delta Exchange.",
        ]
    )
    return send_email(subject, body)


def send_runner_exit_email(
    *,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    runner_lots: int,
    reason: str,
) -> EmailResult:
    trade_label = "LONG" if side == "long" else "SHORT"
    points = (exit_price - entry_price) if side == "long" else (entry_price - exit_price)
    subject = f"LQDTY Runner Exit ({reason}): {runner_lots} lots {symbol} @ {exit_price:.2f}"

    body = "\n".join(
        [
            f"LQDTY Liquidity Strategy — Runner Exit ({reason})",
            "",
            f"Symbol:       {symbol}",
            f"Side:         {trade_label}",
            f"Entry price:  {entry_price:.2f}",
            f"Exit price:   {exit_price:.2f}",
            f"Runner lots:  {runner_lots}",
            f"Points:       {points:.2f}",
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
    strategy_name: str = "15m Previous-Day POC",
) -> EmailResult:
    trade_label = "LONG" if side == "long" else "SHORT"
    points = (exit_price - entry_price) if side == "long" else (entry_price - exit_price)
    subject = f"{strategy_name} Take Profit: {lots} lots {symbol} @ {exit_price:.2f} (+{points:.2f} pts)"

    body = "\n".join(
        [
            f"{strategy_name} — Take Profit",
            "",
            f"Symbol:       {symbol}",
            f"Side:         {trade_label}",
            f"Entry price:  {entry_price:.2f}",
            f"Target:       {target:.2f}",
            f"Exit price:   {exit_price:.2f}",
            f"Lots closed:  {lots}",
            f"Points:       {points:.2f}",
            "",
            "Full position closed on Delta Exchange.",
        ]
    )
    return send_email(subject, body)


def send_test_email() -> EmailResult:
    return send_email(
        subject="Strategy Backtester — Test Email",
        body="This is a test email from your Strategy Backtester live alerts.",
    )
