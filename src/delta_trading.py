from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from delta_rest_client import DeltaRestClient, OrderType

from src.config import get_env

TESTNET_INDIA_URL = "https://cdn-ind.testnet.deltaex.org"
PRODUCTION_INDIA_URL = "https://api.india.delta.exchange"


@dataclass
class DeltaOrderResult:
    success: bool
    symbol: str
    side: str
    size: int
    price: float | None
    order_type: str
    order: dict[str, Any] | None
    position: dict[str, Any] | None
    error: str = ""


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
    """Authenticated Delta Exchange client for demo/live trading."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        symbol: str | None = None,
    ) -> None:
        self.api_key = api_key or get_env("DELTA_API_KEY")
        self.api_secret = api_secret or get_env("DELTA_API_SECRET")
        self.base_url = (base_url or get_env("DELTA_BASE_URL", TESTNET_INDIA_URL)).rstrip("/")
        self.symbol = symbol or get_env("DELTA_SYMBOL", "ETHUSD")
        self._client: DeltaRestClient | None = None
        self._product_cache: dict[str, dict[str, Any]] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    @property
    def client(self) -> DeltaRestClient:
        if not self.is_configured:
            raise RuntimeError(
                "Delta API credentials missing. Set DELTA_API_KEY and DELTA_API_SECRET in .env"
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
        if symbol in self._product_cache:
            return self._product_cache[symbol]

        products = self.client.get_products()
        matches = [product for product in products if product.get("symbol") == symbol]
        if not matches:
            raise RuntimeError(f"Product not found for symbol {symbol}")

        preferred_types = ("perpetual_futures", "futures", "spot")
        product = matches[0]
        for contract_type in preferred_types:
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
                error="",
            )
        except Exception as exc:  # noqa: BLE001
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
        symbol = symbol or self.symbol
        ticker = self.client.get_ticker(symbol)
        mark_price = ticker.get("mark_price") or ticker.get("spot_price")
        if mark_price is None:
            raise RuntimeError(f"Could not fetch mark price for {symbol}")
        return float(mark_price)

    def get_trading_status(self, symbol: str | None = None) -> str:
        return str(self.get_product(symbol).get("trading_status", "unknown"))

    def get_open_position_size(self, symbol: str | None = None) -> int:
        """Signed size: positive = long, negative = short, zero = flat."""
        product_id = self.get_product_id(symbol)
        position = self.client.get_margined_position(product_id)
        if not position:
            return 0
        return int(position.get("size") or 0)

    def get_open_position_lots(self, symbol: str | None = None) -> int:
        return abs(self.get_open_position_size(symbol))

    def close_position_at_market(self, *, symbol: str | None = None) -> DeltaOrderResult:
        symbol = symbol or self.symbol
        try:
            position_size = self.get_open_position_size(symbol)
            if position_size == 0:
                return DeltaOrderResult(
                    success=False,
                    symbol=symbol,
                    side="",
                    size=0,
                    price=None,
                    order_type="market",
                    order=None,
                    position=None,
                    error="No open position to close.",
                )

            trading_status = self.get_trading_status(symbol)
            if trading_status != "operational":
                return DeltaOrderResult(
                    success=False,
                    symbol=symbol,
                    side="sell" if position_size > 0 else "buy",
                    size=abs(position_size),
                    price=None,
                    order_type="market",
                    order=None,
                    position=None,
                    error=(
                        f"{symbol} trading status is '{trading_status}'. "
                        "New orders are blocked until the market is operational."
                    ),
                )

            close_side = "sell" if position_size > 0 else "buy"
            close_size = abs(position_size)
            mark_price = self.get_mark_price(symbol)
            try:
                order = self.place_market_order(
                    size=close_size,
                    side=close_side,
                    symbol=symbol,
                    reduce_only=True,
                )
                order_type = "market"
            except Exception:  # noqa: BLE001
                order = self.place_limit_order(
                    size=close_size,
                    side=close_side,
                    limit_price=mark_price,
                    symbol=symbol,
                    reduce_only=True,
                )
                order_type = f"limit@{mark_price}"

            product_id = self.get_product_id(symbol)
            position = self.client.get_margined_position(product_id)
            return DeltaOrderResult(
                success=True,
                symbol=symbol,
                side=close_side,
                size=close_size,
                price=mark_price,
                order_type=order_type,
                order=order,
                position=position,
                error="",
            )
        except Exception as exc:  # noqa: BLE001
            return DeltaOrderResult(
                success=False,
                symbol=symbol,
                side="",
                size=0,
                price=None,
                order_type="market",
                order=None,
                position=None,
                error=str(exc),
            )

    def place_buy_at_current_price(
        self,
        size: int = 100,
        *,
        symbol: str | None = None,
    ) -> DeltaOrderResult:
        symbol = symbol or self.symbol
        try:
            trading_status = self.get_trading_status(symbol)
            if trading_status != "operational":
                return DeltaOrderResult(
                    success=False,
                    symbol=symbol,
                    side="buy",
                    size=size,
                    price=None,
                    order_type="market",
                    order=None,
                    position=None,
                    error=(
                        f"{symbol} trading status is '{trading_status}'. "
                        "New orders are blocked until the market is operational."
                    ),
                )

            mark_price = self.get_mark_price(symbol)
            try:
                order = self.place_market_order(size=size, side="buy", symbol=symbol)
                order_type = "market"
            except Exception as market_error:  # noqa: BLE001
                order = self.place_limit_order(
                    size=size,
                    side="buy",
                    limit_price=mark_price,
                    symbol=symbol,
                )
                order_type = f"limit@{mark_price}"

            product_id = self.get_product_id(symbol)
            position = self.client.get_margined_position(product_id)
            return DeltaOrderResult(
                success=True,
                symbol=symbol,
                side="buy",
                size=size,
                price=mark_price,
                order_type=order_type,
                order=order,
                position=position,
                error="",
            )
        except Exception as exc:  # noqa: BLE001
            return DeltaOrderResult(
                success=False,
                symbol=symbol,
                side="buy",
                size=size,
                price=None,
                order_type="market",
                order=None,
                position=None,
                error=str(exc),
            )

    def place_market_order(
        self,
        size: int,
        side: str,
        *,
        symbol: str | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        product_id = self.get_product_id(symbol)
        return self.client.place_order(
            product_id=product_id,
            size=size,
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
        product_id = self.get_product_id(symbol)
        return self.client.place_order(
            product_id=product_id,
            size=size,
            side=side,
            limit_price=limit_price,
            order_type=OrderType.LIMIT,
            reduce_only="true" if reduce_only else "false",
        )

    def get_product_tick_size(self, symbol: str | None = None) -> float:
        tick = self.get_product(symbol).get("tick_size")
        return float(tick) if tick else 0.05

    def stop_would_trigger_immediately(
        self,
        stop_side: str,
        stop_price: float,
        mark_price: float,
        *,
        symbol: str | None = None,
    ) -> bool:
        tick = self.get_product_tick_size(symbol)
        if stop_side == "buy":
            return stop_price <= mark_price + tick
        return stop_price >= mark_price - tick

    def place_stop_order(
        self,
        size: int,
        side: str,
        stop_price: float,
        *,
        symbol: str | None = None,
        limit_price: float | None = None,
        reduce_only: bool = True,
        mark_price: float | None = None,
    ) -> dict[str, Any]:
        mark = mark_price if mark_price is not None else self.get_mark_price(symbol)
        if self.stop_would_trigger_immediately(side, stop_price, mark, symbol=symbol):
            raise ValueError(
                f"Stop {side} @ {stop_price:.2f} would trigger immediately (mark {mark:.2f})"
            )

        product_id = self.get_product_id(symbol)
        order: dict[str, Any] = {
            "product_id": product_id,
            "size": int(size),
            "side": side,
            "order_type": OrderType.LIMIT.value,
            "stop_order_type": "stop_loss_order",
            "stop_price": str(stop_price),
            "limit_price": str(limit_price or stop_price),
            "reduce_only": reduce_only,
        }
        return self.client.create_order(order)

    def place_stop_or_market_close(
        self,
        size: int,
        stop_side: str,
        stop_price: float,
        *,
        symbol: str | None = None,
        reduce_only: bool = True,
    ) -> dict[str, Any]:
        """Place stop if valid; otherwise close at market (stop already breached)."""
        mark = self.get_mark_price(symbol)
        try:
            return self.place_stop_order(
                size=size,
                side=stop_side,
                stop_price=stop_price,
                symbol=symbol,
                reduce_only=reduce_only,
                mark_price=mark,
            )
        except ValueError as exc:
            if "would trigger immediately" not in str(exc).lower():
                raise
        except Exception as exc:
            if "immediate_execution_stop_order" not in str(exc).lower():
                raise

        return self.place_market_order(
            size=size,
            side=stop_side,
            symbol=symbol,
            reduce_only=reduce_only,
        )

    def cancel_all_orders(self, symbol: str | None = None) -> dict[str, Any]:
        product_id = self.get_product_id(symbol)
        return self.client.cancel_all_orders({"product_id": product_id})

    def cancel_open_orders(self, symbol: str | None = None) -> None:
        """Cancel all live orders for a symbol (stops + limits)."""
        product_id = self.get_product_id(symbol)
        orders = self.get_open_orders(symbol)
        for order in orders:
            order_id = order.get("id")
            if order_id is not None:
                try:
                    self.client.cancel_order(product_id, order_id)
                except Exception:  # noqa: BLE001
                    continue
        try:
            self.client.cancel_all_orders({"product_id": product_id})
        except Exception:  # noqa: BLE001
            pass

    def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        product_id = self.get_product_id(symbol)
        orders = self.client.get_live_orders(query={"product_id": product_id})
        return orders or []


def is_testnet_url(base_url: str) -> bool:
    return "testnet" in base_url.lower()
