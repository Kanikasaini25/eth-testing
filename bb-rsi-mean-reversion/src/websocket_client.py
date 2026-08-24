"""Public WebSocket ticker/candles with automatic reconnect. REST is the fallback."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

from src.config import CANDLE_RESOLUTION, WS_RECONNECT_SECONDS, Settings
from src.logger import setup_logger

logger = setup_logger()


class TickerFeed:
    def __init__(
        self,
        settings: Settings,
        on_mark: Callable[[float], None] | None = None,
    ) -> None:
        self.settings = settings
        self.on_mark = on_mark
        self._mark: float | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.connected = False

    @property
    def mark_price(self) -> float | None:
        return self._mark

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="bb-rsi-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_loop(self) -> None:
        try:
            import websocket
        except ImportError:
            logger.warning("websocket-client not installed — using REST mark prices only")
            return

        while not self._stop.is_set():
            try:
                self._connect(websocket)
            except Exception as exc:  # noqa: BLE001
                self.connected = False
                logger.warning("WebSocket disconnected (%s) — retrying", exc)
                self._stop.wait(WS_RECONNECT_SECONDS)

    def _connect(self, websocket: Any) -> None:
        subscribe = json.dumps(
            {
                "type": "subscribe",
                "payload": {
                    "channels": [
                        {"name": "v2/ticker", "symbols": [self.settings.symbol]},
                        {"name": f"candlestick_{CANDLE_RESOLUTION}", "symbols": [self.settings.symbol]},
                    ]
                },
            }
        )

        def on_open(ws: Any) -> None:
            self.connected = True
            logger.info("WebSocket connected %s", self.settings.ws_url)
            ws.send(subscribe)

        def on_message(_ws: Any, message: str) -> None:
            self._handle_message(message)

        def on_error(_ws: Any, error: Exception) -> None:
            logger.warning("WebSocket error: %s", error)

        def on_close(_ws: Any, *_args: Any) -> None:
            self.connected = False

        app = websocket.WebSocketApp(
            self.settings.ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        app.run_forever(ping_interval=20, ping_timeout=10)

    def _handle_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        mark = _extract_mark(payload)
        if mark is None:
            return
        self._mark = mark
        if self.on_mark:
            self.on_mark(mark)


def _extract_mark(payload: dict[str, Any]) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in ("mark_price", "close", "price"):
        if payload.get(key) is not None:
            try:
                return float(payload[key])
            except (TypeError, ValueError):
                continue
    candle = payload.get("candle") or payload.get("result") or {}
    if isinstance(candle, dict) and candle.get("close") is not None:
        try:
            return float(candle["close"])
        except (TypeError, ValueError):
            return None
    return None
