from __future__ import annotations

from dataclasses import dataclass, field

from src.config import (
    DEFAULT_NOTIONAL_USD,
    ETH_CONTRACT_VALUE,
    FIXED_LOTS,
    STRATEGY_FUNDING,
    get_env,
    get_env_bool,
    get_env_float,
    get_env_int,
    lots_for_notional,
    symbol_spec,
)


@dataclass
class StrategyParams:
    strategy: str = STRATEGY_FUNDING
    position_lots: int = FIXED_LOTS
    fee_pct_per_side: float = 0.05
    fee_maker_pct: float = 0.02
    maker_on_take_profit: bool = False
    maker_on_entry: bool = False
    gst_pct: float = 0.0
    starting_wallet_usd: float = 10000.0
    contract_value: float = ETH_CONTRACT_VALUE
    funding_threshold_pct: float = 0.005
    funding_confirm_periods: int = 2
    funding_interval_hours: int = 8
    funding_min_settlements: int = 8
    funding_fee_margin: float = 1.0
    funding_futures_maker: bool = True
    funding_exit_confirm: int = 2
    funding_require_momentum: bool = False
    funding_skip_minutes_before_settle: int = 30
    funding_strong_rate_pct: float = 0.02
    futures_symbol: str = "ETHUSD"
    spot_symbol: str = "ETH_INR"

    def hedge_qty(self) -> float:
        """Units of the underlying the spot leg must buy or sell."""
        return self.position_lots * self.contract_value

    def notional_usd(self, price: float) -> float:
        return self.hedge_qty() * price


@dataclass
class EntrySignal:
    strategy: str
    side: str
    entry_ts: str
    entry_price: float
    stop_loss: float
    target: float
    order_type: str
    reason: str
    extras: dict = field(default_factory=dict)
    lots: int = 0


def default_params(
    strategy: str | None = None,
    lots: int | None = None,
    symbol: str | None = None,
    price: float | None = None,
    notional_usd: float | None = None,
) -> StrategyParams:
    """Build params for one book.

    Pass ``price`` to size by notional instead of a fixed lot count, so every
    symbol carries the same USD exposure regardless of its contract value.
    """
    chosen = (strategy or get_env("STRATEGY", STRATEGY_FUNDING)).strip().lower()
    if chosen != STRATEGY_FUNDING:
        chosen = STRATEGY_FUNDING
    futures = (symbol or get_env("DELTA_SYMBOL", "ETHUSD")).strip().upper()
    spec = symbol_spec(futures)
    if lots is not None:
        sized = int(lots)
    elif price:
        target = notional_usd if notional_usd is not None else get_env_float(
            "NOTIONAL_USD", DEFAULT_NOTIONAL_USD
        )
        sized = lots_for_notional(futures, price, target)
    else:
        sized = get_env_int("POSITION_LOTS", FIXED_LOTS)
    spot = get_env("SPOT_SYMBOL") if futures == "ETHUSD" else ""
    return StrategyParams(
        strategy=chosen,
        position_lots=sized,
        contract_value=spec.contract_value,
        funding_threshold_pct=get_env_float("FUNDING_THRESHOLD_PCT", 0.005),
        funding_confirm_periods=get_env_int("FUNDING_CONFIRM_PERIODS", 2),
        funding_interval_hours=get_env_int("FUNDING_INTERVAL_HOURS", 8),
        funding_min_settlements=get_env_int("FUNDING_MIN_SETTLEMENTS", 8),
        funding_fee_margin=get_env_float("FUNDING_FEE_MARGIN", 1.0),
        funding_futures_maker=get_env_bool("FUNDING_FUTURES_MAKER", True),
        funding_exit_confirm=get_env_int("FUNDING_EXIT_CONFIRM", 2),
        funding_require_momentum=get_env_bool("FUNDING_REQUIRE_MOMENTUM", False),
        funding_skip_minutes_before_settle=get_env_int("FUNDING_SKIP_MINUTES_BEFORE_SETTLE", 30),
        funding_strong_rate_pct=get_env_float("FUNDING_STRONG_RATE_PCT", 0.02),
        futures_symbol=futures,
        spot_symbol=spot or spec.spot,
    )
