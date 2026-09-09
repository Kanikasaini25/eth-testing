from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from delta_rest_client import DeltaRestClient, OrderType

from src.config import get_env, INDIA_LIVE_URL
from src.symbols import resolve_delta_symbol

TESTNET_INDIA_URL = "https://cdn-ind.testnet.deltaex.org"
PRODUCTION_INDIA_URL = INDIA_LIVE_URL


@dataclass
class DeltaAccountSnapshot:
    connected: bool
    base_url: str
    symbol: str
    product_id: int | None
    wallet_balances: list[dict[str, Any]]
    position: dict[str, Any] | None
    ticker: dict[str, Any] | None
    error: str = ""


class DeltaTradingClient:
    """Authenticated Delta India client for live order placement."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        symbol: str | None = None,
    ) -> None:
        self.api_key = api_key or get_env("DELTA_API_KEY")
        self.api_secret = api_secret or get_env("DELTA_API_SECRET")
        self.base_url = (
            base_url or get_env("DELTA_BASE_URL", PRODUCTION_INDIA_URL)
        ).rstrip("/")
        requested = symbol or get_env("DELTA_SYMBOL", "ETHUSD")
        self.symbol, _notice = resolve_delta_symbol(requested)
        self._client: DeltaRestClient | None = None
        self._product_cache: dict[str, dict[str, Any]] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    @property
    def client(self) -> DeltaRestClient:
        if not self.is_configured:
            raise RuntimeError(
                "Set DELTA_API_KEY and DELTA_API_SECRET in .env before going live."
            )
        if self._client is None:
            self._client = DeltaRestClient(
                base_url=self.base_url,
                api_key=self.api_key,
                api_secret=self.api_secret,
            )
        return self._client

    def get_product(self, symbol: str | None = None) -> dict[str, Any]:
        symbol = symbol or self.symbol
        cached = self._product_cache.get(symbol)
        if cached is not None:
            return cached
        products = self.client.get_products()
        matches = [item for item in products if item.get("symbol") == symbol]
        if not matches:
            raise RuntimeError(f"Product not found for {symbol}")
        product = matches[0]
        for contract_type in ("perpetual_futures", "futures"):
            typed = next(
                (item for item in matches if item.get("contract_type") == contract_type),
                None,
            )
            if typed is not None:
                product = typed
                break
        self._product_cache[symbol] = product
        return product

    def get_product_id(self, symbol: str | None = None) -> int:
        return int(self.get_product(symbol)["id"])

    def get_product_tick_size(self, symbol: str | None = None) -> float:
        tick = self.get_product(symbol).get("tick_size")
        return float(tick) if tick else 0.05

    def test_connection(self) -> DeltaAccountSnapshot:
        if not self.is_configured:
            return DeltaAccountSnapshot(
                connected=False,
                base_url=self.base_url,
                symbol=self.symbol,
                product_id=None,
                wallet_balances=[],
                position=None,
                ticker=None,
                error="API key or secret not configured",
            )
        try:
            product = self.get_product()
            product_id = int(product["id"])
            balances = self.client.get_all_wallet_balances()
            position = self.client.get_margined_position(product_id)
            ticker = self.client.get_ticker(self.symbol)
            return DeltaAccountSnapshot(
                connected=True,
                base_url=self.base_url,
                symbol=self.symbol,
                product_id=product_id,
                wallet_balances=balances or [],
                position=position,
                ticker=ticker,
            )
        except Exception as exc:
            return DeltaAccountSnapshot(
                connected=False,
                base_url=self.base_url,
                symbol=self.symbol,
                product_id=None,
                wallet_balances=[],
                position=None,
                ticker=None,
                error=str(exc),
            )

    def get_mark_price(self, symbol: str | None = None) -> float:
        ticker = self.client.get_ticker(symbol or self.symbol)
        mark = ticker.get("mark_price") or ticker.get("spot_price") or ticker.get("close")
        if mark is None:
            raise RuntimeError(f"No mark price for {symbol or self.symbol}")
        return float(mark)

    def get_open_position_size(self, symbol: str | None = None) -> int:
        position = self.client.get_margined_position(self.get_product_id(symbol))
        if not position:
            return 0
        return int(position.get("size") or 0)

    def get_position_entry_price(self, symbol: str | None = None) -> float | None:
        position = self.client.get_margined_position(self.get_product_id(symbol))
        if not position:
            return None
        raw = position.get("entry_price")
        return float(raw) if raw not in (None, "") else None

    def place_market_order(
        self,
        size: int,
        side: str,
        *,
        symbol: str | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        return self.client.place_order(
            product_id=self.get_product_id(symbol),
            size=int(size),
            side=side,
            order_type=OrderType.MARKET,
            reduce_only="true" if reduce_only else "false",
        )

    def place_limit_order(
        self,
        size: int,
        side: str,
        limit_price: float,
        *,
        symbol: str | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        return self.client.place_order(
            product_id=self.get_product_id(symbol),
            size=int(size),
            side=side,
            limit_price=limit_price,
            order_type=OrderType.LIMIT,
            reduce_only="true" if reduce_only else "false",
        )

    def place_stop_order(
        self,
        size: int,
        side: str,
        stop_price: float,
        *,
        symbol: str | None = None,
        reduce_only: bool = True,
    ) -> dict[str, Any]:
        order = {
            "product_id": self.get_product_id(symbol),
            "size": int(size),
            "side": side,
            "order_type": OrderType.MARKET.value,
            "stop_order_type": "stop_loss_order",
            "stop_price": str(stop_price),
            "reduce_only": reduce_only,
        }
        return self.client.create_order(order)

    def cancel_open_orders(self, symbol: str | None = None) -> None:
        product_id = self.get_product_id(symbol)
        orders = self.client.get_live_orders(query={"product_id": product_id}) or []
        for order in orders:
            order_id = order.get("id")
            if order_id is None:
                continue
            try:
                self.client.cancel_order(product_id, order_id)
            except Exception as exc:
                print(f"Cancel failed for {order_id}: {exc}")
        try:
            self.client.cancel_all_orders({"product_id": product_id})
        except Exception as exc:
            print(f"Cancel-all failed: {exc}")


def is_testnet_url(base_url: str) -> bool:
    return "testnet" in base_url.lower()
