from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from src.backtest import run_backtest
from src.config import (
    DEFAULT_NOTIONAL_USD,
    STRATEGY_FUNDING,
    format_ist,
    live_state_path,
    now_ist,
    symbol_spec,
)
from src.delta_data import DeltaExchangeClient, closed_ohlcv
from src.delta_trading import DeltaTradingClient
from src.email_notify import notify_event
from src.funding_strategy import (
    FundingScreen,
    detect_funding_signal,
    funding_rate_pct,
    reading_rates,
    screen_funding_history,
)
from src.strategy import EntrySignal, StrategyParams, default_params

CANDLE_API_URL = "https://api.india.delta.exchange"
LOOKBACK_DAYS = 30
SCREEN_DAYS = 365


def _now_label(symbol: str = "") -> str:
    stamp = now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
    return f"{stamp} | {symbol}" if symbol else stamp


def round_to_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return round(price, 2)
    return round(round(price / tick) * tick, 8)


def _notify(subject: str, lines: list[str]) -> str:
    result = notify_event(subject, lines)
    return result.message if result.success else f"Email not sent: {result.message}"


@dataclass
class LiveState:
    last_signal_ts: str = ""
    stage: str = "flat"
    side: str = ""
    entry_price: float = 0.0
    lots: int = 0
    spot_qty: float = 0.0
    pending_fut_side: str = ""
    pending_spot_side: str = ""
    pending_cover: bool = False


def load_state(strategy: str, symbol: str = "") -> LiveState:
    path = live_state_path(strategy, symbol)
    if not path.exists():
        return LiveState()
    payload = json.loads(path.read_text())
    allowed = set(LiveState.__dataclass_fields__)
    return LiveState(**{key: value for key, value in payload.items() if key in allowed})


def save_state(strategy: str, state: LiveState, symbol: str = "") -> None:
    path = live_state_path(strategy, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2))


class LiveStrategyRunner:
    def __init__(self, params: StrategyParams, symbol: str = "") -> None:
        self.params = params
        self.symbol = (symbol or params.futures_symbol).upper()
        self.candles = DeltaExchangeClient(base_url=CANDLE_API_URL)
        self.broker = DeltaTradingClient(symbol=self.symbol)
        self.state = load_state(params.strategy, self.symbol)

    def _save(self) -> None:
        save_state(self.params.strategy, self.state, self.symbol)

    def latest_signal(self) -> tuple[EntrySignal | None, str, str]:
        """Decide from the same FUNDING: series the backtest reads.

        The ticker's own ``funding_rate`` field disagrees with that series in
        sign as well as level (ETHUSD ticker read +0.0009% while the funding
        candles read -0.048%), so sizing off the ticker would open the hedge
        the wrong way round on every entry.
        """
        funding = closed_ohlcv(
            self.candles.fetch_funding_ohlcv(self.symbol, days=LOOKBACK_DAYS, resolution="1h"),
            "1h",
        )
        if not funding:
            return None, now_ist().isoformat(), "no funding candles"
        ticker = self.candles.fetch_ticker(self.symbol)
        price = float(ticker.get("mark_price") or ticker.get("close") or 0.0)
        last_ts = str(funding[-1]["timestamp"])
        rate = funding_rate_pct(funding[-1])
        hedge_side = self.state.side if self.state.stage in {"carry", "reverse"} else ""
        signal = detect_funding_signal(
            funding,
            [{"timestamp": last_ts, "close": price}],
            self.params,
            position_side=hedge_side,
        )
        recent = reading_rates(funding, max(self.params.funding_exit_confirm, 2))
        note = (
            f"funding {rate:+.5f}% last {[round(item, 5) for item in recent]} px {price:,.2f}"
        )
        return signal, last_ts, note

    def tick(self, dry_run: bool = True) -> list[str]:
        pending = self._complete_pending(dry_run)
        if pending:
            return pending
        signal, last_ts, note = self.latest_signal()
        actions = [
            f"{_now_label(self.symbol)} | {note} | {format_ist(last_ts)} | stage {self.state.stage}"
        ]
        if signal is None:
            return actions
        return actions + self._handle_entry(signal, dry_run)

    def _maker_limit(self, fut_side: str, fallback: float) -> float:
        tick = self.broker.get_product_tick_size()
        ticker = self.candles.fetch_ticker(self.symbol)
        quotes = ticker.get("quotes") or {}
        bid = float(quotes.get("best_bid") or ticker.get("close") or fallback)
        ask = float(quotes.get("best_ask") or ticker.get("close") or fallback)
        raw = bid if fut_side == "sell" else ask
        return round_to_tick(raw or fallback, tick)

    def _complete_pending(self, dry_run: bool) -> list[str]:
        if self.state.stage != "pending_futures" or not self.state.pending_fut_side:
            return []
        if dry_run:
            return []
        size = abs(self.broker.get_open_position_size())
        lots = self.state.lots or self.params.position_lots
        if size < lots:
            return [
                f"{_now_label(self.symbol)} | waiting for post-only futures fill ({size}/{lots})"
            ]
        if self.state.pending_cover:
            spot_side = self.state.pending_spot_side or "sell"
            qty = self.state.spot_qty or self.params.hedge_qty()
            try:
                self.broker.place_market_order(qty, spot_side, symbol=self.params.spot_symbol)
            except Exception as exc:
                return self._spot_leg_failed(spot_side, qty, exc, closing=True)
            opened = self.state.side or "carry"
            self.state = LiveState(last_signal_ts=self.state.last_signal_ts)
            self._save()
            return [f"{opened} closed after maker futures fill"]
        spot_side = self.state.pending_spot_side
        qty = self.params.hedge_qty()
        try:
            self.broker.place_market_order(qty, spot_side, symbol=self.params.spot_symbol)
        except Exception as exc:
            return self._spot_leg_failed(spot_side, qty, exc, closing=False)
        self.state.stage = self.state.side
        self.state.spot_qty = qty
        self.state.pending_fut_side = ""
        self.state.pending_spot_side = ""
        self._save()
        return [f"Spot {spot_side} {qty} after maker futures fill"]

    def _spot_leg_failed(
        self,
        spot_side: str,
        qty: float,
        exc: Exception,
        *,
        closing: bool,
    ) -> list[str]:
        """Never leave the futures leg naked when the spot hedge cannot fill.

        The futures order has already filled at this point, so an unhedged
        position is outright price risk. Close it and go flat instead.
        """
        unwind = "buy" if self.state.pending_fut_side == "sell" else "sell"
        lots = self.state.lots or self.params.position_lots
        self._unwind_leg(self.symbol, lots, unwind)
        self.state = LiveState(last_signal_ts=self.state.last_signal_ts)
        self._save()
        stage = "cover" if closing else "entry"
        alert = _notify(
            f"[LIVE] {self.symbol} spot leg failed on {stage}",
            [
                f"Spot {spot_side} {qty} {self.params.spot_symbol} failed: {exc}",
                f"Futures unwound with {unwind} {lots}; now flat.",
            ],
        )
        return [
            f"Spot {spot_side} {qty} {self.params.spot_symbol} failed: {exc}",
            f"Futures unwound ({unwind} {lots}) to avoid a naked leg",
            alert,
        ]

    def _unwind_leg(self, symbol: str, size: float | int, side: str) -> None:
        try:
            self.broker.place_market_order(size, side, symbol=symbol)
        except Exception as exc:
            print(f"Unwind {symbol} {side} failed: {exc}")

    def _handle_entry(self, signal: EntrySignal | None, dry_run: bool) -> list[str]:
        if signal is None:
            return []
        if signal.entry_ts == self.state.last_signal_ts and signal.side != "cover":
            return ["Signal already handled"]
        lots = signal.lots or self.params.position_lots
        mode = "DRY-RUN" if dry_run else "LIVE"
        lines = [
            f"{_now_label(self.symbol)} | {mode} {signal.side} {signal.order_type} {lots} lots",
            f"  Time: {signal.entry_ts}  px {signal.entry_price:.2f}  {signal.reason}",
        ]
        if dry_run:
            if signal.side == "cover":
                self.state = LiveState(last_signal_ts=signal.entry_ts)
            else:
                self.state = LiveState(
                    last_signal_ts=signal.entry_ts,
                    stage=signal.side,
                    side=signal.side,
                    entry_price=signal.entry_price,
                    lots=lots,
                    spot_qty=self.params.hedge_qty() if signal.side in {"carry", "reverse"} else 0.0,
                )
            self._save()
            lines.append(_notify(f"[{mode}] {self.symbol} {signal.side}", lines))
            return lines
        return lines + self._execute(signal)

    def _execute(self, signal: EntrySignal) -> list[str]:
        if signal.side in {"carry", "reverse"}:
            return self._enter_hedge(signal)
        if signal.side == "cover":
            return self._exit_hedge(signal)
        return [f"Skip unknown side {signal.side}"]

    def _enter_hedge(self, signal: EntrySignal) -> list[str]:
        lots = self.params.position_lots
        qty = self.params.hedge_qty()
        open_size = self.broker.get_open_position_size()
        if abs(open_size) > 0:
            return [f"Skip {signal.side}: {self.symbol} already {open_size} lots"]
        fut_side = "sell" if signal.side == "carry" else "buy"
        spot_side = "buy" if signal.side == "carry" else "sell"
        unwind = "buy" if fut_side == "sell" else "sell"
        try:
            if self.params.funding_futures_maker:
                limit = self._maker_limit(fut_side, signal.entry_price)
                self.broker.place_limit_order(lots, fut_side, limit, symbol=self.symbol, post_only=True)
            else:
                self.broker.place_market_order(lots, fut_side, symbol=self.symbol)
        except Exception as exc:
            return [f"{signal.side} futures {fut_side} failed: {exc}"]
        filled = abs(self.broker.get_open_position_size()) >= lots
        if self.params.funding_futures_maker and not filled:
            self.state = LiveState(
                last_signal_ts=signal.entry_ts,
                stage="pending_futures",
                side=signal.side,
                entry_price=signal.entry_price,
                lots=lots,
                pending_fut_side=fut_side,
                pending_spot_side=spot_side,
            )
            self._save()
            return [f"Post-only futures {fut_side} {lots} resting; spot waits for fill"]
        try:
            self.broker.place_market_order(qty, spot_side, symbol=self.params.spot_symbol)
        except Exception as exc:
            self._unwind_leg(self.symbol, lots, unwind)
            return [f"{signal.side} spot {spot_side} failed, futures unwound: {exc}"]
        self.state = LiveState(
            last_signal_ts=signal.entry_ts,
            stage=signal.side,
            side=signal.side,
            entry_price=signal.entry_price,
            lots=lots,
            spot_qty=qty,
        )
        self._save()
        mail = _notify(
            f"[LIVE] {signal.side} {self.symbol}",
            [f"Futures {fut_side} {lots} + spot {spot_side} {qty} {self.params.spot_symbol}"],
        )
        return [f"{signal.side}: futures {fut_side} {lots}, spot {spot_side} {qty}", mail]

    def _exit_hedge(self, signal: EntrySignal) -> list[str]:
        lots = self.state.lots or self.params.position_lots
        qty = self.state.spot_qty or self.params.hedge_qty()
        opened = self.state.side or "carry"
        fut_side = "buy" if opened == "carry" else "sell"
        spot_side = "sell" if opened == "carry" else "buy"
        if self.params.funding_futures_maker:
            limit = self._maker_limit(fut_side, signal.entry_price)
            self.broker.place_limit_order(
                lots, fut_side, limit, symbol=self.symbol, reduce_only=True, post_only=True
            )
            if abs(self.broker.get_open_position_size()) > 0:
                self.state.stage = "pending_futures"
                self.state.pending_fut_side = fut_side
                self.state.pending_spot_side = spot_side
                self.state.pending_cover = True
                self._save()
                return [f"Post-only cover {fut_side} {lots} resting; spot waits for fill"]
        else:
            self.broker.place_market_order(lots, fut_side, symbol=self.symbol, reduce_only=True)
        self.broker.place_market_order(qty, spot_side, symbol=self.params.spot_symbol)
        self.state = LiveState(last_signal_ts=signal.entry_ts)
        self._save()
        mail = _notify(f"[LIVE] {self.symbol} hedge exit", [f"Funding flipped; closed {opened}"])
        return [f"{opened} closed (futures {fut_side} + spot {spot_side})", mail]


def screen_symbol(symbol: str, days: int = SCREEN_DAYS) -> FundingScreen:
    """Preflight a book before trading it: is its funding one-sided enough?"""
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)
    rows = client.fetch_funding_ohlcv(symbol, days=days, resolution="1h")
    return screen_funding_history(rows, symbol=symbol)


def build_runners(
    symbols: tuple[str, ...] | list[str],
    *,
    lots: int | None = None,
    notional_usd: float = DEFAULT_NOTIONAL_USD,
) -> list[LiveStrategyRunner]:
    """One runner per symbol, each sized to the same USD notional."""
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)
    runners: list[LiveStrategyRunner] = []
    for symbol in symbols:
        upper = symbol.strip().upper()
        price = None
        if lots is None:
            ticker = client.fetch_ticker(upper)
            price = float(ticker.get("mark_price") or ticker.get("close") or 0.0)
        params = default_params(
            strategy=STRATEGY_FUNDING,
            lots=lots,
            symbol=upper,
            price=price,
            notional_usd=notional_usd,
        )
        runners.append(LiveStrategyRunner(params=params, symbol=upper))
    return runners


def describe_book(params: StrategyParams, price: float = 0.0) -> str:
    spec = symbol_spec(params.futures_symbol)
    line = (
        f"{params.futures_symbol}: {params.position_lots} lots "
        f"= {params.hedge_qty():g} {spec.spot.split('_')[0]} vs {spec.spot}"
    )
    if price:
        line += f" (~${params.notional_usd(price):,.0f})"
    return line


def scan_closed_bars(rows: list[dict], params: StrategyParams, funding_rows: list[dict] | None = None):
    entries: list[EntrySignal] = []
    result = run_backtest(rows, params, funding_rows=funding_rows, entry_log=entries)
    last_ts = rows[-1]["timestamp"] if rows else "no data"
    signal = entries[-1] if entries and entries[-1].entry_ts == last_ts else None
    return signal, result, last_ts
