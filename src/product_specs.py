from __future__ import annotations

from dataclasses import dataclass

import requests

from src.config import get_candle_base_url, get_env
from src.symbols import resolve_delta_symbol

# Delta India products: quoted, settled, and margined in USD (not INR).
# XAUUSD is NOT listed — use PAXGUSD (PAX Gold) or XAUTUSD (Tether Gold).
DEFAULT_SPECS = {
    "ETHUSD": {
        "contract_value": 0.01,
        "settlement_currency": "USD",
        "taker_fee_rate": 0.0005,
        "maker_fee_rate": 0.0002,
        "tick_size": 0.05,
    },
    "BTCUSD": {
        "contract_value": 0.001,
        "settlement_currency": "USD",
        "taker_fee_rate": 0.0005,
        "maker_fee_rate": 0.0002,
        "tick_size": 0.5,
    },
    "PAXGUSD": {
        "contract_value": 0.001,
        "settlement_currency": "USD",
        "taker_fee_rate": 0.0001,
        "maker_fee_rate": 0.0001,
        "tick_size": 0.01,
    },
    "XAUTUSD": {
        "contract_value": 0.001,
        "settlement_currency": "USD",
        "taker_fee_rate": 0.0001,
        "maker_fee_rate": 0.0001,
        "tick_size": 0.01,
    },
}


@dataclass(frozen=True)
class ProductSpecs:
    symbol: str
    contract_value: float
    settlement_currency: str
    taker_fee_rate: float
    maker_fee_rate: float
    tick_size: float

    # Back-compat alias used by older call sites.
    @property
    def contract_value_eth(self) -> float:
        return self.contract_value

    @property
    def usd_per_point_per_lot(self) -> float:
        """USD P&L for a $1 underlying price move on one lot."""
        return self.contract_value

    def notional_usd(self, lots: int, price: float) -> float:
        return abs(lots) * self.contract_value * price

    def gross_pnl_usd(self, lots: int, points: float) -> float:
        return points * lots * self.contract_value

    def trading_fee_usd(self, lots: int, price: float, rate: float, *, gst_pct: float = 0.0) -> float:
        gst = 1.0 + gst_pct / 100.0
        return self.notional_usd(lots, price) * rate * gst


def fetch_product_specs(symbol: str | None = None) -> ProductSpecs:
    requested = (symbol or get_env("DELTA_SYMBOL", "ETHUSD")).strip().upper()
    symbol, _notice = resolve_delta_symbol(requested)
    fallback = DEFAULT_SPECS.get(symbol, DEFAULT_SPECS["ETHUSD"])
    try:
        response = requests.get(
            f"{get_candle_base_url()}/v2/products/{symbol}",
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(payload)
        product = payload["result"]
        return ProductSpecs(
            symbol=symbol,
            contract_value=float(product.get("contract_value", fallback["contract_value"])),
            settlement_currency="USD",
            taker_fee_rate=float(product.get("taker_commission_rate", fallback["taker_fee_rate"])),
            maker_fee_rate=float(product.get("maker_commission_rate", fallback["maker_fee_rate"])),
            tick_size=float(product.get("tick_size", fallback["tick_size"])),
        )
    except Exception:
        return ProductSpecs(
            symbol=symbol,
            contract_value=fallback["contract_value"],
            settlement_currency=fallback["settlement_currency"],
            taker_fee_rate=fallback["taker_fee_rate"],
            maker_fee_rate=fallback["maker_fee_rate"],
            tick_size=fallback["tick_size"],
        )


def _env_bool(name: str, default: bool) -> bool:
    raw = get_env(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on"}


def _parse_exit_pcts(raw: str) -> tuple[float, ...]:
    """Parse '30,40,10,10' → T1–T4 percents of original size (T5 = remainder)."""
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    if len(parts) < 4:
        return (30.0, 40.0, 10.0, 10.0)
    return tuple(float(p) for p in parts[:4])


def lots_for_one_usd_per_point(specs: ProductSpecs, *, usd_per_point: float = 1.0) -> int:
    """Lots so a $1 underlying move ≈ `usd_per_point` USD P&L.

    PAXGUSD/XAUTUSD: contract 0.001 → 1000 lots = $1 per $1 move.
    ETHUSD: contract 0.01 → 100 lots = $1 per $1 move.
    """
    per_lot = float(specs.usd_per_point_per_lot)
    if per_lot <= 0:
        return 1
    return max(1, int(round(float(usd_per_point) / per_lot)))


def backtest_params_from_env(symbol: str | None = None) -> "BacktestParams":
    from src.backtest import BacktestParams

    specs = fetch_product_specs(symbol)
    wallet = float(get_env("STARTING_WALLET_USD", "10000") or "10000")
    # Default: size so $1 price move = $1 USD profit (unless POSITION_LOTS is set)
    target_usd = float(get_env("TARGET_USD_PER_POINT", "1") or "1")
    auto_lots = lots_for_one_usd_per_point(specs, usd_per_point=target_usd)
    raw_lots = get_env("POSITION_LOTS", "")
    lots = int(raw_lots) if raw_lots else auto_lots
    return BacktestParams(
        position_lots=max(lots, 1),
        starting_wallet_usd=wallet,
        usd_per_point_per_lot=specs.usd_per_point_per_lot,
        fee_pct_per_side=specs.taker_fee_rate * 100.0,
        fee_maker_pct=specs.maker_fee_rate * 100.0,
        target_points=float(get_env("TARGET_POINTS", "40") or "40"),
        trend_lookback=int(get_env("TREND_LOOKBACK", "6") or "6"),
        min_confirm_body=float(get_env("MIN_CONFIRM_BODY", "0.5") or "0.5"),
        partial_exit_pct=float(get_env("PARTIAL_EXIT_PCT", "30") or "30"),
        max_targets=int(get_env("MAX_TARGETS", "5") or "5"),
        exit_scale_pcts=_parse_exit_pcts(
            get_env("EXIT_SCALE_PCTS", "30,40,10,10")
        ),
        min_shadow_ratio=float(get_env("MIN_SHADOW_RATIO", "2.5") or "2.5"),
        min_pattern_points=float(get_env("MIN_PATTERN_POINTS", "2.0") or "2.0"),
        max_sl_points=float(get_env("MAX_SL_POINTS", "25") or "25"),
        min_rr_ratio=float(get_env("MIN_RR_RATIO", "1.5") or "1.5"),
        breakeven_points=float(get_env("BREAKEVEN_POINTS", "15") or "15"),
        min_overlay_votes=int(get_env("MIN_OVERLAY_VOTES", "2") or "2"),
        require_double_confirm=False,
        require_volume_spike=False,
        require_rsi_extreme=False,
        require_ema_trend=False,
        require_swing_confluence=False,
        # Gold overlays
        use_ema_regime=_env_bool("USE_EMA_REGIME", True),
        ema_fast=int(get_env("EMA_FAST", "20") or "20"),
        ema_slow=int(get_env("EMA_SLOW", "50") or "50"),
        use_adx_filter=_env_bool("USE_ADX_FILTER", True),
        adx_period=int(get_env("ADX_PERIOD", "14") or "14"),
        adx_min=float(get_env("ADX_MIN", "20") or "20"),
        use_donchian_filter=_env_bool("USE_DONCHIAN_FILTER", True),
        donchian_period=int(get_env("DONCHIAN_PERIOD", "20") or "20"),
        use_bollinger_rsi=_env_bool("USE_BOLLINGER_RSI", True),
        bb_period=int(get_env("BB_PERIOD", "20") or "20"),
        bb_std=float(get_env("BB_STD", "2.0") or "2.0"),
        rsi_period=int(get_env("RSI_PERIOD", "14") or "14"),
        rsi_oversold=float(get_env("RSI_OVERSOLD", "25") or "25"),
        rsi_overbought=float(get_env("RSI_OVERBOUGHT", "75") or "75"),
        use_atr_stops=_env_bool("USE_ATR_STOPS", True),
        atr_period=int(get_env("ATR_PERIOD", "14") or "14"),
        atr_stop_mult=float(get_env("ATR_STOP_MULT", "1.5") or "1.5"),
        atr_target_mult=float(get_env("ATR_TARGET_MULT", "2.0") or "2.0"),
        atr_max_risk_mult=float(get_env("ATR_MAX_RISK_MULT", "2.0") or "2.0"),
        use_adaptive_targets=_env_bool("USE_ADAPTIVE_TARGETS", True),
        use_session_filter=_env_bool("USE_SESSION_FILTER", True),
        session_london_start=int(get_env("SESSION_LONDON_START", "7") or "7"),
        session_london_end=int(get_env("SESSION_LONDON_END", "10") or "10"),
        session_overlap_start=int(get_env("SESSION_OVERLAP_START", "12") or "12"),
        session_overlap_end=int(get_env("SESSION_OVERLAP_END", "16") or "16"),
        scalper_offer=True,
        maker_on_take_profit=True,
    )
