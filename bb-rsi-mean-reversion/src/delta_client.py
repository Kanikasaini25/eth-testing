"""Delta REST market + trading methods used only by the BB/RSI bot."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.config import BAR_SECONDS, CANDLE_LOOKBACK, CANDLE_RESOLUTION, DEFAULT_CONTRACT_ETH, Settings
from src.errors import DeltaAPIError
from src.http import DeltaHttp


class DeltaClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = DeltaHttp(settings.rest_url, settings.api_key, settings.api_secret)
        self._product: dict[str, Any] | None = None

    def get_product(self) -> dict[str, Any]:
        if self._product is not None:
            return self._product
        products = self.http.request("GET", "/v2/products")
        matches = [item for item in products if item.get("symbol") == self.settings.symbol]
        if not matches:
            raise DeltaAPIError(f"Product not found: {self.settings.symbol}")
        preferred = ("perpetual_futures", "futures")
        product = matches[0]
        for contract_type in preferred:
            typed = next((item for item in matches if item.get("contract_type") == contract_type), None)
            if typed is not None:
                product = typed
                break
        self._product = product
        return product

    def product_id(self) -> int:
        return int(self.get_product()["id"])

    def contract_eth(self) -> float:
        product = self.get_product()
        for key in ("contract_value", "contract_unit_currency", "position_size"):
            raw = product.get(key)
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if 0 < value <= 1:
                return value
        return DEFAULT_CONTRACT_ETH

    def tick_size(self) -> float:
        tick = self.get_product().get("tick_size")
        return float(tick) if tick else 0.05

    def trading_status(self) -> str:
        return str(self.get_product().get("trading_status", "unknown"))

    def get_mark_price(self) -> float:
        ticker = self.http.request("GET", f"/v2/tickers/{self.settings.symbol}")
        mark = ticker.get("mark_price") or ticker.get("close") or ticker.get("spot_price")
        if mark is None:
            raise DeltaAPIError(f"No mark price for {self.settings.symbol}")
        return float(mark)

    def fetch_closed_candles(self, limit: int = CANDLE_LOOKBACK) -> list[dict[str, Any]]:
        end = int(datetime.now(timezone.utc).timestamp())
        start = end - (limit + 5) * BAR_SECONDS
        raw = self.http.request(
            "GET",
            "/v2/history/candles",
            params={
                "symbol": self.settings.symbol,
                "resolution": CANDLE_RESOLUTION,
                "start": start,
                "end": end,
            },
        )
        rows: list[dict[str, Any]] = []
        seen: set[int] = set()
        for candle in sorted(raw or [], key=lambda item: item["time"]):
            ts = int(candle["time"])
            if ts in seen:
                continue
            seen.add(ts)
            bar_end = ts + BAR_SECONDS
            if bar_end > end:
                continue
            rows.append(
                {
                    "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": float(candle.get("volume") or 0),
                }
            )
        return rows[-limit:]

    def get_position_size(self) -> int:
        product_id = self.product_id()
        try:
            position = self.http.request(
                "GET",
                "/v2/positions",
                params={"product_id": product_id},
                signed=True,
            )
        except DeltaAPIError:
            position = self.http.request(
                "GET",
                "/v2/positions/margined",
                params={"product_id": product_id},
                signed=True,
            )
        if not position:
            return 0
        if isinstance(position, list):
            position = next((item for item in position if int(item.get("product_id") or 0) == product_id), None)
        if not position:
            return 0
        return int(position.get("size") or 0)

    def get_open_orders(self) -> list[dict[str, Any]]:
        orders = self.http.request(
            "GET",
            "/v2/orders",
            params={"product_id": self.product_id(), "state": "open"},
            signed=True,
        )
        return orders or []

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("product_id", self.product_id())
        return self.http.request("POST", "/v2/orders", json_body=payload, signed=True)

    def place_bracket(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("product_id", self.product_id())
        return self.http.request("POST", "/v2/orders/bracket", json_body=payload, signed=True)

    def cancel_open_orders(self) -> None:
        product_id = self.product_id()
        try:
            self.http.request("DELETE", "/v2/orders/all", json_body={"product_id": product_id}, signed=True)
        except DeltaAPIError:
            orders = self.http.request(
                "GET",
                "/v2/orders",
                params={"product_id": product_id, "state": "open"},
                signed=True,
            ) or []
            for order in orders:
                order_id = order.get("id")
                if order_id is None:
                    continue
                try:
                    self.http.request(
                        "DELETE",
                        "/v2/orders",
                        json_body={"id": order_id, "product_id": product_id},
                        signed=True,
                    )
                except DeltaAPIError:
                    continue

    def close_position_market(self) -> None:
        size = self.get_position_size()
        if size == 0:
            return
        side = "sell" if size > 0 else "buy"
        self.place_order(
            {
                "size": abs(size),
                "side": side,
                "order_type": "market_order",
                "reduce_only": True,
            }
        )
