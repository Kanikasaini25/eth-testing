from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.config import get_env

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - package is Windows-only
    mt5 = None  # type: ignore


TIMEFRAME_MAP = {
    "1m": "TIMEFRAME_M1",
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "45m": "TIMEFRAME_M30",  # closest available; strategy still uses closed bars
    "1h": "TIMEFRAME_H1",
    "1d": "TIMEFRAME_D1",
    "1w": "TIMEFRAME_W1",
}


@dataclass
class Mt5AccountSnapshot:
    connected: bool
    login: int
    server: str
    name: str
    balance: float
    equity: float
    currency: str
    leverage: int
    symbol: str
    bid: float
    ask: float
    error: str = ""


def mt5_available() -> bool:
    return mt5 is not None


class Mt5Broker:
    """Local MetaTrader 5 bridge for PDMBulls (demo or live) on this laptop."""

    def __init__(
        self,
        *,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        symbol: str | None = None,
        path: str | None = None,
    ) -> None:
        self.login = int(login if login is not None else (get_env("MT5_LOGIN") or "0") or 0)
        self.password = password if password is not None else get_env("MT5_PASSWORD")
        self.server = (server if server is not None else get_env("MT5_SERVER", "PDMBulls-ServerMT5")).strip()
        self.symbol = (symbol if symbol is not None else get_env("MT5_SYMBOL", "XAUUSD")).strip().upper()
        self.path = (path if path is not None else get_env("MT5_PATH")).strip() or None
        self._connected = False

    @property
    def is_configured(self) -> bool:
        return bool(self.login and self.password and self.server)

    def connect(self) -> None:
        if mt5 is None:
            raise RuntimeError(
                "MetaTrader5 Python package is not installed or not supported on this OS. "
                "Install MetaTrader 5 on Windows, log into PDMBulls, then: pip install MetaTrader5"
            )
        if self._connected:
            return
        kwargs: dict[str, Any] = {}
        if self.path:
            kwargs["path"] = self.path
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        authorized = mt5.login(self.login, password=self.password, server=self.server)
        if not authorized:
            err = mt5.last_error()
            mt5.shutdown()
            raise RuntimeError(
                f"MT5 login failed for {self.login} @ {self.server}: {err}. "
                "Open MT5 on this laptop, confirm demo login works, then retry."
            )
        if not mt5.symbol_select(self.symbol, True):
            mt5.shutdown()
            raise RuntimeError(f"MT5 symbol not found or not visible: {self.symbol}")
        self._connected = True

    def shutdown(self) -> None:
        if mt5 is not None and self._connected:
            mt5.shutdown()
        self._connected = False

    def snapshot(self) -> Mt5AccountSnapshot:
        try:
            self.connect()
            info = mt5.account_info()
            tick = mt5.symbol_info_tick(self.symbol)
            if info is None:
                return Mt5AccountSnapshot(
                    connected=False,
                    login=self.login,
                    server=self.server,
                    name="",
                    balance=0.0,
                    equity=0.0,
                    currency="",
                    leverage=0,
                    symbol=self.symbol,
                    bid=0.0,
                    ask=0.0,
                    error=str(mt5.last_error()),
                )
            return Mt5AccountSnapshot(
                connected=True,
                login=int(info.login),
                server=str(info.server),
                name=str(info.name),
                balance=float(info.balance),
                equity=float(info.equity),
                currency=str(info.currency),
                leverage=int(info.leverage),
                symbol=self.symbol,
                bid=float(tick.bid) if tick else 0.0,
                ask=float(tick.ask) if tick else 0.0,
            )
        except Exception as exc:
            return Mt5AccountSnapshot(
                connected=False,
                login=self.login,
                server=self.server,
                name="",
                balance=0.0,
                equity=0.0,
                currency="",
                leverage=0,
                symbol=self.symbol,
                bid=0.0,
                ask=0.0,
                error=str(exc),
            )

    def _timeframe(self, resolution: str):
        attr = TIMEFRAME_MAP.get(resolution, "TIMEFRAME_M15")
        return getattr(mt5, attr)

    def fetch_ohlcv(self, resolution: str, bars: int = 500) -> list[dict]:
        self.connect()
        rates = mt5.copy_rates_from_pos(self.symbol, self._timeframe(resolution), 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No MT5 candles for {self.symbol} {resolution}: {mt5.last_error()}")
        rows: list[dict] = []
        for rate in rates:
            ts = datetime.fromtimestamp(int(rate["time"]), tz=timezone.utc).isoformat()
            rows.append(
                {
                    "timestamp": ts,
                    "open": float(rate["open"]),
                    "high": float(rate["high"]),
                    "low": float(rate["low"]),
                    "close": float(rate["close"]),
                    "volume": float(rate["tick_volume"]),
                }
            )
        return rows

    def symbol_info(self) -> Any:
        self.connect()
        info = mt5.symbol_info(self.symbol)
        if info is None:
            raise RuntimeError(f"No symbol info for {self.symbol}")
        return info

    def point(self) -> float:
        return float(self.symbol_info().point)

    def digits(self) -> int:
        return int(self.symbol_info().digits)

    def volume_step(self) -> float:
        return float(self.symbol_info().volume_step or 0.01)

    def normalize_volume(self, volume: float) -> float:
        step = self.volume_step()
        info = self.symbol_info()
        vmin = float(info.volume_min or step)
        vmax = float(info.volume_max or volume)
        steps = round(volume / step)
        out = max(vmin, min(vmax, steps * step))
        return float(f"{out:.2f}")

    def normalize_price(self, price: float) -> float:
        return round(price, self.digits())

    def position_volume(self) -> float:
        self.connect()
        positions = mt5.positions_get(symbol=self.symbol) or []
        return float(sum(float(pos.volume) for pos in positions))

    def position_side(self) -> str:
        self.connect()
        positions = mt5.positions_get(symbol=self.symbol) or []
        if not positions:
            return ""
        typ = int(positions[0].type)
        return "long" if typ == mt5.POSITION_TYPE_BUY else "short"

    def cancel_pending(self) -> None:
        self.connect()
        orders = mt5.orders_get(symbol=self.symbol) or []
        for order in orders:
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
            }
            mt5.order_send(request)

    def place_market(
        self,
        side: str,
        volume: float,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str = "pattern",
    ) -> dict[str, Any]:
        self.connect()
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            raise RuntimeError(f"No tick for {self.symbol}")
        volume = self.normalize_volume(volume)
        order_type = mt5.ORDER_TYPE_BUY if side == "long" else mt5.ORDER_TYPE_SELL
        price = tick.ask if side == "long" else tick.bid
        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": int(get_env("MT5_DEVIATION", "40") or "40"),
            "magic": int(get_env("MT5_MAGIC", "260903") or "260903"),
            "comment": comment[:30],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(),
        }
        if stop_loss is not None:
            request["sl"] = self.normalize_price(stop_loss)
        if take_profit is not None:
            request["tp"] = self.normalize_price(take_profit)
        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError(f"MT5 order_send returned None: {mt5.last_error()}")
        payload = result._asdict() if hasattr(result, "_asdict") else dict(result)
        if int(payload.get("retcode", -1)) != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 order rejected: {payload}")
        return payload

    def modify_position_sl_tp(self, stop_loss: float | None = None, take_profit: float | None = None) -> None:
        self.connect()
        positions = mt5.positions_get(symbol=self.symbol) or []
        for pos in positions:
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": self.symbol,
                "position": pos.ticket,
                "sl": self.normalize_price(stop_loss if stop_loss is not None else pos.sl),
                "tp": self.normalize_price(take_profit if take_profit is not None else pos.tp),
            }
            result = mt5.order_send(request)
            if result is None or int(result.retcode) != mt5.TRADE_RETCODE_DONE:
                raise RuntimeError(f"MT5 SL/TP modify failed: {result}")

    def close_partial(self, volume: float) -> dict[str, Any]:
        self.connect()
        positions = mt5.positions_get(symbol=self.symbol) or []
        if not positions:
            raise RuntimeError("No open MT5 position to close")
        pos = positions[0]
        side = "short" if int(pos.type) == mt5.POSITION_TYPE_BUY else "long"
        tick = mt5.symbol_info_tick(self.symbol)
        price = tick.bid if side == "short" else tick.ask
        volume = self.normalize_volume(min(volume, float(pos.volume)))
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_SELL if side == "short" else mt5.ORDER_TYPE_BUY,
            "position": pos.ticket,
            "price": price,
            "deviation": int(get_env("MT5_DEVIATION", "40") or "40"),
            "magic": int(get_env("MT5_MAGIC", "260903") or "260903"),
            "comment": "partial_exit",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(),
        }
        result = mt5.order_send(request)
        if result is None or int(result.retcode) != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 partial close failed: {result}")
        return result._asdict() if hasattr(result, "_asdict") else dict(result)

    def _filling_mode(self) -> int:
        info = self.symbol_info()
        filling = int(getattr(info, "filling_mode", 0) or 0)
        # Prefer IOC then FOK then RETURN depending on symbol flags.
        if filling & 1:
            return mt5.ORDER_FILLING_FOK
        if filling & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN
