"""Trade log + grand-total rows for the Streamlit backtest UI."""

from __future__ import annotations

from collections import defaultdict

from src.backtest import BacktestResult, Trade
from src.session import format_ist_clock, parse_bar_time, trading_day


def format_usd(amount: float) -> str:
    return f"${amount:+,.2f}"


def format_fee(amount: float) -> str:
    return f"${amount:,.2f}"


def trade_rows(result: BacktestResult) -> list[dict]:
    rows: list[dict] = []
    for index, trade in enumerate(result.trades, start=1):
        rows.append(_trade_row(index, trade))
    if rows:
        rows.append(_grand_total_row(result))
    return rows


def _ohlc(trade: Trade) -> str:
    return (
        f"{trade.entry_open:.2f} / {trade.entry_high:.2f} / "
        f"{trade.entry_low:.2f} / {trade.entry_price:.2f}"
    )


def _trade_row(index: int, trade: Trade) -> dict:
    return {
        "#": index,
        "Side": trade.side.upper(),
        "Session": trade.session,
        "Entry": format_ist_clock(trade.entry_ts),
        "Exit": format_ist_clock(trade.exit_ts),
        "Entry OHLC": _ohlc(trade),
        "Entry $": round(trade.entry_price, 2),
        "SL $": round(trade.stop_price, 2),
        "Exit $": round(trade.exit_price, 2),
        "Lots": trade.lots,
        "Points": round(trade.points, 2),
        "Gross P/L": format_usd(trade.gross_pnl),
        "Entry fee": format_fee(trade.entry_fee),
        "Exit fee": format_fee(trade.exit_fee),
        "Net P/L": format_usd(trade.pnl_usd),
        "Wallet": format_usd(trade.wallet_balance),
        "Reason": trade.exit_reason,
    }


def _grand_total_row(result: BacktestResult) -> dict:
    return {
        "#": "",
        "Side": "GRAND TOTAL",
        "Session": "",
        "Entry": "",
        "Exit": "",
        "Entry OHLC": "",
        "Entry $": "",
        "SL $": "",
        "Exit $": "",
        "Lots": sum(trade.lots for trade in result.trades),
        "Points": round(sum(trade.points for trade in result.trades), 2),
        "Gross P/L": format_usd(result.gross_pnl),
        "Entry fee": format_fee(sum(trade.entry_fee for trade in result.trades)),
        "Exit fee": format_fee(sum(trade.exit_fee for trade in result.trades)),
        "Net P/L": format_usd(result.total_pnl),
        "Wallet": format_usd(result.final_wallet),
        "Reason": f"{result.wins}W / {result.losses}L",
    }


def daily_rows(result: BacktestResult) -> list[dict]:
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in result.trades:
        grouped[trading_day(parse_bar_time(trade.entry_ts))].append(trade)
    rows: list[dict] = []
    for day in sorted(grouped):
        legs = grouped[day]
        pnl = sum(leg.pnl_usd for leg in legs)
        fees = sum(leg.entry_fee + leg.exit_fee for leg in legs)
        wins = sum(1 for leg in legs if leg.pnl_usd > 0)
        losses = sum(1 for leg in legs if leg.pnl_usd < 0)
        rows.append(
            {
                "IST day": day,
                "Trades": len(legs),
                "Wins": wins,
                "Losses": losses,
                "Fees": format_fee(fees),
                "Day P/L ($)": format_usd(pnl),
            }
        )
    if rows:
        rows.append(
            {
                "IST day": "GRAND TOTAL",
                "Trades": len(result.trades),
                "Wins": result.wins,
                "Losses": result.losses,
                "Fees": format_fee(result.total_fees),
                "Day P/L ($)": format_usd(result.total_pnl),
            }
        )
    return rows
