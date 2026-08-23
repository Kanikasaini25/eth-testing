"""Bar-by-bar 1m backtest for SMA Bollinger + RSI mean reversion."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import (
    BB_PERIOD,
    DAILY_MAX_LOSS_USD,
    DAILY_TRADE_CAP,
    DEFAULT_CONTRACT_ETH,
    FIXED_LOTS,
    HTF_BARS,
    LOSS_COOLDOWN_MINUTES,
    MAX_PROFIT_USD,
    MAX_SESSION_STOPS,
    PER_TRADE_STOP_USD,
    PROFIT_LOCK_USD,
    RSI_PERIOD,
    TAKER_FEE_PCT,
    TAKE_PROFIT_USD,
)
from src.risk import (
    bar_stop_hit,
    bar_target_hit,
    build_trade_plan,
    price_pnl_usd,
    trading_fee_usd,
    trail_lock_price,
)
from src.session import can_open_new_trade, in_loss_cooldown, parse_bar_time, session_key, utc_day
from src.strategy import evaluate_closed_candle

WARMUP = max(BB_PERIOD, RSI_PERIOD + 1, HTF_BARS + 1)


@dataclass
class SimPosition:
    side: str
    entry_price: float
    lots: int
    stop_price: float
    take_profit_price: float
    profit_lock_price: float
    max_profit_price: float
    contract_eth: float
    entry_ts: str
    rsi: float
    lower_band: float
    upper_band: float
    entry_fee: float = 0.0
    profit_locked: bool = False
    entry_open: float = 0.0
    entry_high: float = 0.0
    entry_low: float = 0.0


@dataclass
class Trade:
    side: str
    entry_ts: str
    exit_ts: str
    entry_price: float
    exit_price: float
    lots: int
    stop_price: float
    take_profit_price: float
    pnl_usd: float
    wallet_balance: float
    exit_reason: str
    rsi: float
    points: float
    gross_pnl: float = 0.0
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    entry_open: float = 0.0
    entry_high: float = 0.0
    entry_low: float = 0.0


@dataclass
class BacktestConfig:
    starting_wallet: float = 10_000.0
    daily_trade_cap: int = DAILY_TRADE_CAP
    daily_max_loss_usd: float = DAILY_MAX_LOSS_USD
    per_trade_stop_usd: float = PER_TRADE_STOP_USD
    take_profit_usd: float = TAKE_PROFIT_USD
    profit_lock_usd: float = PROFIT_LOCK_USD
    max_profit_usd: float = MAX_PROFIT_USD
    contract_eth: float = DEFAULT_CONTRACT_ETH
    tick_size: float = 0.05
    lots: int = FIXED_LOTS
    fee_pct_per_side: float = TAKER_FEE_PCT
    enable_trailing_lock: bool = False
    trail_to_max_profit: bool = False
    net_of_fees: bool = True
    loss_cooldown_minutes: int = LOSS_COOLDOWN_MINUTES
    max_session_stops: int = MAX_SESSION_STOPS


@dataclass
class BacktestResult:
    symbol: str
    days: int
    candle_count: int
    start_ts: str
    end_ts: str
    starting_wallet: float
    final_wallet: float
    total_pnl: float
    wins: int
    losses: int
    win_rate: float
    max_drawdown: float
    buy_hold_usd: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    skipped_cap: int = 0
    skipped_kill: int = 0
    gross_pnl: float = 0.0
    total_fees: float = 0.0


def run_backtest(
    candles: list[dict],
    *,
    symbol: str,
    days: int,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    cfg = config or BacktestConfig()
    engine = _Engine(candles, cfg)
    engine.run()
    return engine.result(symbol, days)


class _Engine:
    def __init__(self, candles: list[dict], config: BacktestConfig) -> None:
        self.candles = candles
        self.cfg = config
        self.wallet = config.starting_wallet
        self.position: SimPosition | None = None
        self.trades: list[Trade] = []
        self.equity: list[float] = [config.starting_wallet]
        self.day = ""
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.kill = False
        self.skipped_cap = 0
        self.skipped_kill = 0
        self.last_loss_ts: str = ""
        self.session_key = ""
        self.session_sls = 0
        self.session_profit = False
        self.peak = config.starting_wallet
        self.max_dd = 0.0

    def run(self) -> None:
        for index, bar in enumerate(self.candles):
            if index < WARMUP:
                continue
            self._roll_day(bar["timestamp"])
            if self.position is not None:
                self._manage(bar)
            if self.position is None:
                self._maybe_enter(index, bar)
            self._mark_equity(bar)

        if self.position is not None and self.candles:
            self._close(self.candles[-1], float(self.candles[-1]["close"]), "end_of_data")

    def result(self, symbol: str, days: int) -> BacktestResult:
        wins = sum(1 for trade in self.trades if trade.pnl_usd > 0)
        losses = sum(1 for trade in self.trades if trade.pnl_usd < 0)
        total = len(self.trades)
        first = float(self.candles[0]["close"]) if self.candles else 0.0
        last = float(self.candles[-1]["close"]) if self.candles else 0.0
        buy_hold = (last - first) * 1.0
        gross = sum(trade.gross_pnl for trade in self.trades)
        fees = sum(trade.entry_fee + trade.exit_fee for trade in self.trades)
        return BacktestResult(
            symbol=symbol,
            days=days,
            candle_count=len(self.candles),
            start_ts=self.candles[0]["timestamp"] if self.candles else "",
            end_ts=self.candles[-1]["timestamp"] if self.candles else "",
            starting_wallet=self.cfg.starting_wallet,
            final_wallet=round(self.wallet, 2),
            total_pnl=round(self.wallet - self.cfg.starting_wallet, 2),
            wins=wins,
            losses=losses,
            win_rate=round((wins / total) * 100.0, 2) if total else 0.0,
            max_drawdown=round(self.max_dd, 2),
            buy_hold_usd=round(buy_hold, 2),
            trades=self.trades,
            equity_curve=self.equity,
            skipped_cap=self.skipped_cap,
            skipped_kill=self.skipped_kill,
            gross_pnl=round(gross, 2),
            total_fees=round(fees, 2),
        )

    def _roll_day(self, timestamp: str) -> None:
        day = utc_day(parse_bar_time(timestamp))
        if self.day == day:
            return
        self.day = day
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.kill = False

    def _roll_session(self, moment) -> None:
        key = session_key(moment)
        if key == self.session_key:
            return
        self.session_key = key
        self.session_sls = 0
        self.session_profit = False

    def _mark_equity(self, bar: dict) -> None:
        unrealized = 0.0
        if self.position is not None:
            unrealized = price_pnl_usd(
                self.position.side,
                self.position.entry_price,
                float(bar["close"]),
                self.position.lots,
                self.position.contract_eth,
            )
            exit_fee = trading_fee_usd(
                float(bar["close"]),
                self.position.lots,
                self.position.contract_eth,
                self.cfg.fee_pct_per_side,
            )
            unrealized -= exit_fee
        equity = self.wallet + unrealized
        self.equity.append(round(equity, 4))
        self.peak = max(self.peak, equity)
        self.max_dd = max(self.max_dd, self.peak - equity)

    def _manage(self, bar: dict) -> None:
        position = self.position
        if position is None:
            return
        fill = _resolve_exit(position, bar, self.cfg)
        if fill is not None:
            self._close(bar, fill[0], fill[1])
            return
        unrealized = price_pnl_usd(
            position.side,
            position.entry_price,
            float(bar["close"]),
            position.lots,
            position.contract_eth,
        )
        exit_fee = trading_fee_usd(
            float(bar["close"]),
            position.lots,
            position.contract_eth,
            self.cfg.fee_pct_per_side,
        )
        if self.daily_pnl + unrealized - exit_fee <= -abs(self.cfg.daily_max_loss_usd):
            self._close(bar, float(bar["close"]), "kill_switch")

    def _maybe_enter(self, index: int, bar: dict) -> None:
        bar_time = parse_bar_time(bar["timestamp"])
        if not can_open_new_trade(bar_time):
            return
        self._roll_session(bar_time)
        if self.session_profit:
            return
        if self.session_sls >= self.cfg.max_session_stops:
            return
        if in_loss_cooldown(self.last_loss_ts, bar_time, self.cfg.loss_cooldown_minutes):
            return
        signal = evaluate_closed_candle(
            self.candles[: index + 1],
            after_session_stop=self.session_sls > 0,
        )
        if signal is None:
            return
        if self.kill:
            self.skipped_kill += 1
            return
        if self.trades_today >= self.cfg.daily_trade_cap:
            self.skipped_cap += 1
            return
        plan = build_trade_plan(
            side=signal.side,
            entry_price=float(bar["close"]),
            candle_low=float(bar["low"]),
            candle_high=float(bar["high"]),
            risk_usd=self.cfg.per_trade_stop_usd,
            take_profit_usd=self.cfg.take_profit_usd,
            profit_lock_usd=self.cfg.profit_lock_usd,
            max_profit_usd=self.cfg.max_profit_usd,
            contract_eth=self.cfg.contract_eth,
            tick_size=self.cfg.tick_size,
            lots=self.cfg.lots,
            fee_pct_per_side=self.cfg.fee_pct_per_side,
            net_of_fees=self.cfg.net_of_fees,
        )
        entry_fee = trading_fee_usd(
            plan.entry_price,
            plan.lots,
            plan.contract_eth,
            self.cfg.fee_pct_per_side,
        )
        self.wallet = round(self.wallet - entry_fee, 4)
        self.daily_pnl = round(self.daily_pnl - entry_fee, 4)
        self.position = SimPosition(
            side=plan.side,
            entry_price=plan.entry_price,
            lots=plan.lots,
            stop_price=plan.stop_price,
            take_profit_price=plan.take_profit_price,
            profit_lock_price=plan.profit_lock_price,
            max_profit_price=plan.max_profit_price,
            contract_eth=plan.contract_eth,
            entry_ts=bar["timestamp"],
            rsi=signal.indicators.rsi,
            lower_band=signal.indicators.lower_band,
            upper_band=signal.indicators.upper_band,
            entry_fee=entry_fee,
            entry_open=float(bar["open"]),
            entry_high=float(bar["high"]),
            entry_low=float(bar["low"]),
        )
        self.trades_today += 1

    def _close(self, bar: dict, exit_price: float, reason: str) -> None:
        position = self.position
        if position is None:
            return
        gross = price_pnl_usd(
            position.side, position.entry_price, exit_price, position.lots, position.contract_eth
        )
        exit_fee = trading_fee_usd(
            exit_price, position.lots, position.contract_eth, self.cfg.fee_pct_per_side
        )
        net = gross - position.entry_fee - exit_fee
        self.wallet = round(self.wallet + gross - exit_fee, 4)
        self.daily_pnl = round(self.daily_pnl + gross - exit_fee, 4)
        points = exit_price - position.entry_price
        if position.side == "short":
            points = -points
        self.trades.append(
            Trade(
                side=position.side,
                entry_ts=position.entry_ts,
                exit_ts=bar["timestamp"],
                entry_price=position.entry_price,
                exit_price=exit_price,
                lots=position.lots,
                stop_price=position.stop_price,
                take_profit_price=position.take_profit_price,
                pnl_usd=round(net, 4),
                wallet_balance=self.wallet,
                exit_reason=reason,
                rsi=round(position.rsi, 2),
                points=round(points, 4),
                gross_pnl=round(gross, 4),
                entry_fee=round(position.entry_fee, 4),
                exit_fee=round(exit_fee, 4),
                entry_open=position.entry_open,
                entry_high=position.entry_high,
                entry_low=position.entry_low,
            )
        )
        if net < 0:
            self.last_loss_ts = position.entry_ts
            if reason == "stop_loss":
                self._roll_session(parse_bar_time(bar["timestamp"]))
                self.session_sls += 1
        elif net > 0:
            self._roll_session(parse_bar_time(bar["timestamp"]))
            self.session_profit = True
        self.position = None
        if self.daily_pnl <= -abs(self.cfg.daily_max_loss_usd):
            self.kill = True


def _resolve_exit(position: SimPosition, bar: dict, cfg: BacktestConfig) -> tuple[float, str] | None:
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    if bar_stop_hit(position.side, low, high, position.stop_price):
        reason = "profit_lock" if position.profit_locked else "stop_loss"
        return position.stop_price, reason
    if cfg.enable_trailing_lock and not position.profit_locked:
        if bar_target_hit(position.side, low, high, position.profit_lock_price):
            # Arm the +$5 stop on this bar. Do not exit here — the same candle
            # that first reaches +5 almost always also traded below +5.
            position.profit_locked = True
            position.stop_price = position.profit_lock_price
    if bar_target_hit(position.side, low, high, position.max_profit_price):
        return position.max_profit_price, "max_profit"
    if not cfg.trail_to_max_profit and bar_target_hit(
        position.side, low, high, position.take_profit_price
    ):
        return position.take_profit_price, "take_profit"
    if cfg.trail_to_max_profit and position.profit_locked:
        position.stop_price = trail_lock_price(
            position.side, close, position.profit_lock_price, position.entry_price
        )
    return None
