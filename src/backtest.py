"""Backtest ETH India volume-bias trades on historical candles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from src.config import get_env
from src.delta_data import DeltaExchangeClient
from src.eth_volume_strategy import (
    CLOSE_TARGET_PCT,
    DEFAULT_ENTRY_HOUR_IST,
    DEFAULT_ENTRY_RESOLUTION,
    DEFAULT_POSITION_LOTS,
    DEFAULT_PULLBACK_RESOLUTION,
    day_limit_reached,
    favorable_move_pct,
    is_tighter_stop,
    measure_volume_bias,
    pullback_and_confirmation,
    pullback_stop_loss,
    split_session_bars,
    stop_is_valid,
    target_price,
    trail_stop_price,
)
from src.live_state import env_float, env_int
from src.timezone import india_calendar_day

ETH_PER_LOT = 0.01  # Delta ETHUSD: 1 lot = 0.01 ETH → 100 lots = 1 ETH
INDIA_LIVE_DATA_URL = "https://api.india.delta.exchange"


@dataclass
class BacktestTrade:
    india_day: str
    side: str
    bias_label: str
    buy_volume: float
    sell_volume: float
    entry_ts: str
    exit_ts: str
    entry_price: float
    exit_price: float
    stop_loss: float
    target: float
    pullback_high: float
    pullback_low: float
    lots: int
    points: float
    pnl_usd: float
    wallet_balance: float
    exit_reason: str


@dataclass
class BacktestResult:
    symbol: str
    data_url: str
    resolution: str
    candle_count: int
    start_day: str
    end_day: str
    trades: list[BacktestTrade] = field(default_factory=list)
    starting_wallet: float = 10000.0
    ending_wallet: float = 10000.0
    total_pnl_usd: float = 0.0
    total_points: float = 0.0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    win_rate: float = 0.0
    avg_pnl_usd: float = 0.0
    max_drawdown_usd: float = 0.0
    profit_factor: float = 0.0


def points_for_side(side: str, entry_price: float, exit_price: float) -> float:
    if side == "long":
        return round(exit_price - entry_price, 2)
    return round(entry_price - exit_price, 2)


def pnl_usd(points: float, lots: int) -> float:
    return round(points * lots * ETH_PER_LOT, 2)


def unique_india_days(rows: list[dict]) -> list[str]:
    days: list[str] = []
    seen: set[str] = set()
    for row in rows:
        day = india_calendar_day(row["timestamp"])
        if day in seen:
            continue
        seen.add(day)
        days.append(day)
    return days


def _rows_after(rows: list[dict], timestamp: str) -> list[dict]:
    return [row for row in rows if row["timestamp"] > timestamp]


def _bar_hits(side: str, row: dict, stop_loss: float, target: float) -> str:
    high = float(row["high"])
    low = float(row["low"])
    if side == "long":
        stop_hit = low <= stop_loss
        target_hit = high >= target
    else:
        stop_hit = high >= stop_loss
        target_hit = low <= target
    if stop_hit and target_hit:
        return "stop_loss"
    if stop_hit:
        return "stop_loss"
    if target_hit:
        return "take_profit"
    return ""


def _bar_adverse_hits_stop(side: str, row: dict, stop_loss: float) -> bool:
    if side == "long":
        return float(row["low"]) <= stop_loss
    return float(row["high"]) >= stop_loss


def resolve_exit(
    side: str,
    stop_loss: float,
    target: float,
    manage_bars: list[dict],
    *,
    entry_price: float,
) -> tuple[float, str, str]:
    """Scan 1m bars after entry. Trail SL on favorable extremes; same-bar SL+TP counts as stop."""
    current_stop = stop_loss
    initial_stop = stop_loss
    for row in manage_bars:
        hit = _bar_hits(side, row, current_stop, target)
        if hit == "stop_loss":
            return current_stop, hit, str(row["timestamp"])
        if hit == "take_profit":
            return target, hit, str(row["timestamp"])
        extreme = float(row["high"] if side == "long" else row["low"])
        move_pct = favorable_move_pct(side, entry_price, extreme)
        new_stop = trail_stop_price(side, entry_price, initial_stop, move_pct)
        if is_tighter_stop(side, new_stop, current_stop):
            current_stop = new_stop
            if _bar_adverse_hits_stop(side, row, current_stop):
                return current_stop, "stop_loss", str(row["timestamp"])
    last = manage_bars[-1]
    return float(last["close"]), "end_of_data", str(last["timestamp"])


def _summarize(result: BacktestResult) -> BacktestResult:
    trades = result.trades
    result.ending_wallet = trades[-1].wallet_balance if trades else result.starting_wallet
    result.total_pnl_usd = round(result.ending_wallet - result.starting_wallet, 2)
    result.total_points = round(sum(trade.points for trade in trades), 2)
    result.wins = sum(1 for trade in trades if trade.pnl_usd > 0)
    result.losses = sum(1 for trade in trades if trade.pnl_usd < 0)
    result.flats = sum(1 for trade in trades if trade.pnl_usd == 0)
    result.win_rate = round((result.wins / len(trades)) * 100, 2) if trades else 0.0
    result.avg_pnl_usd = round(result.total_pnl_usd / len(trades), 2) if trades else 0.0
    gross_wins = sum(trade.pnl_usd for trade in trades if trade.pnl_usd > 0)
    gross_losses = abs(sum(trade.pnl_usd for trade in trades if trade.pnl_usd < 0))
    result.profit_factor = round(gross_wins / gross_losses, 2) if gross_losses else (0.0 if not gross_wins else 999.0)
    peak = result.starting_wallet
    max_dd = 0.0
    for trade in trades:
        peak = max(peak, trade.wallet_balance)
        max_dd = max(max_dd, peak - trade.wallet_balance)
    result.max_drawdown_usd = round(max_dd, 2)
    return result


def simulate_day(
    pullback_rows: list[dict],
    entry_rows: list[dict],
    day: str,
    *,
    wallet: float,
    entry_hour_ist: int,
    target_pct: float,
    lots: int,
    pullback_resolution: str = DEFAULT_PULLBACK_RESOLUTION,
) -> list[BacktestTrade]:
    measured = measure_volume_bias(split_session_bars(pullback_rows, day, entry_hour_ist)[0])
    if not measured.side:
        return []
    trades: list[BacktestTrade] = []
    after_timestamp = ""
    wins = 0
    losses = 0
    while True:
        pullback, confirm = pullback_and_confirmation(
            pullback_rows,
            entry_rows,
            day,
            measured.side,
            entry_hour_ist,
            pullback_resolution,
            after_timestamp,
        )
        if pullback is None or confirm is None:
            break
        after_timestamp = pullback.timestamp
        entry_price = float(confirm["close"])
        stop_loss = pullback_stop_loss(pullback, measured.side)
        if not stop_is_valid(measured.side, entry_price, stop_loss):
            continue
        target = target_price(measured.side, entry_price, target_pct)
        manage_bars = _rows_after(entry_rows, str(confirm["timestamp"]))
        if not manage_bars:
            exit_price, reason, exit_ts = entry_price, "end_of_data", str(confirm["timestamp"])
        else:
            exit_price, reason, exit_ts = resolve_exit(
                measured.side,
                stop_loss,
                target,
                manage_bars,
                entry_price=entry_price,
            )
        points = points_for_side(measured.side, entry_price, exit_price)
        trade_pnl = pnl_usd(points, lots)
        wallet = round(wallet + trade_pnl, 2)
        trades.append(
            BacktestTrade(
                india_day=day,
                side=measured.side,
                bias_label=measured.label,
                buy_volume=measured.buy_volume,
                sell_volume=measured.sell_volume,
                entry_ts=str(confirm["timestamp"]),
                exit_ts=exit_ts,
                entry_price=entry_price,
                exit_price=exit_price,
                stop_loss=stop_loss,
                target=target,
                pullback_high=pullback.high,
                pullback_low=pullback.low,
                lots=lots,
                points=points,
                pnl_usd=trade_pnl,
                wallet_balance=wallet,
                exit_reason=reason,
            )
        )
        if trade_pnl > 0:
            wins += 1
        elif trade_pnl < 0:
            losses += 1
        if day_limit_reached(wins, losses):
            break
    return trades


def backtest_volume_bias(
    pullback_rows: list[dict],
    entry_rows: list[dict] | None = None,
    *,
    symbol: str = "ETHUSD",
    data_url: str = INDIA_LIVE_DATA_URL,
    resolution: str = f"{DEFAULT_PULLBACK_RESOLUTION}+{DEFAULT_ENTRY_RESOLUTION}",
    entry_hour_ist: int = DEFAULT_ENTRY_HOUR_IST,
    target_pct: float = CLOSE_TARGET_PCT,
    lots: int = DEFAULT_POSITION_LOTS,
    starting_wallet: float = 10000.0,
    pullback_resolution: str = DEFAULT_PULLBACK_RESOLUTION,
) -> BacktestResult:
    entry_rows = entry_rows if entry_rows is not None else pullback_rows
    days = unique_india_days(pullback_rows)
    result = BacktestResult(
        symbol=symbol,
        data_url=data_url,
        resolution=resolution,
        candle_count=len(entry_rows),
        start_day=days[0] if days else "",
        end_day=days[-1] if days else "",
        starting_wallet=starting_wallet,
        ending_wallet=starting_wallet,
    )
    wallet = starting_wallet
    for day in days:
        day_trades = simulate_day(
            pullback_rows,
            entry_rows,
            day,
            wallet=wallet,
            entry_hour_ist=entry_hour_ist,
            target_pct=target_pct,
            lots=lots,
            pullback_resolution=pullback_resolution,
        )
        for trade in day_trades:
            wallet = trade.wallet_balance
            result.trades.append(trade)
    return _summarize(result)


def run_india_live_backtest(
    *,
    symbol: str,
    start_day: date,
    end_day: date,
    starting_wallet: float,
) -> BacktestResult:
    if end_day < start_day:
        raise ValueError("End date must be on or after start date")
    data_url = get_env("DELTA_DATA_BASE_URL", INDIA_LIVE_DATA_URL) or INDIA_LIVE_DATA_URL
    pullback_resolution = (
        get_env("ETH_PULLBACK_RESOLUTION", DEFAULT_PULLBACK_RESOLUTION) or DEFAULT_PULLBACK_RESOLUTION
    )
    entry_resolution = get_env("ETH_ENTRY_RESOLUTION", DEFAULT_ENTRY_RESOLUTION) or DEFAULT_ENTRY_RESOLUTION
    client = DeltaExchangeClient(base_url=data_url.rstrip("/"))
    start_date = start_day - timedelta(days=1)
    pullback_rows = client.fetch_historical_ohlcv(
        symbol=symbol,
        resolution=pullback_resolution,
        start_date=start_date,
        end_date=end_day,
    )
    entry_rows = client.fetch_historical_ohlcv(
        symbol=symbol,
        resolution=entry_resolution,
        start_date=start_date,
        end_date=end_day,
    )
    start_label = start_day.isoformat()
    end_label = end_day.isoformat()
    pullback_rows = [
        row for row in pullback_rows if start_label <= india_calendar_day(row["timestamp"]) <= end_label
    ]
    entry_rows = [
        row for row in entry_rows if start_label <= india_calendar_day(row["timestamp"]) <= end_label
    ]
    result = backtest_volume_bias(
        pullback_rows,
        entry_rows,
        symbol=symbol,
        data_url=data_url.rstrip("/"),
        resolution=f"{pullback_resolution}+{entry_resolution}",
        entry_hour_ist=env_int("ETH_ENTRY_HOUR_IST", DEFAULT_ENTRY_HOUR_IST),
        target_pct=env_float("ETH_TARGET_PCT", CLOSE_TARGET_PCT),
        lots=env_int("ETH_POSITION_LOTS", DEFAULT_POSITION_LOTS),
        starting_wallet=starting_wallet,
        pullback_resolution=pullback_resolution,
    )
    result.start_day = start_label
    result.end_day = end_label
    return result
