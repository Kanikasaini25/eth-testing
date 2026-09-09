"""Hammer / Shooting Star entry with gold production overlays.

Structure (common live gold algo pattern):
  regime filter (EMA + ADX + optional Donchian) +
  entry trigger (Hammer / Shooting Star) +
  optional mean-reversion confirm (Bollinger + RSI) +
  ATR-scaled stop / target +
  London / NY session window
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.indicators import (
    adx,
    atr,
    bollinger,
    donchian_prior,
    ema,
    in_gold_session,
    rsi,
)
from src.strategy import EntrySignal, is_green, is_red
from src.swings import epoch_of


@dataclass
class IndicatorCache:
    """Precomputed series so each bar does O(1) lookups."""

    ema_fast: list[float | None] = field(default_factory=list)
    ema_slow: list[float | None] = field(default_factory=list)
    adx: list[float | None] = field(default_factory=list)
    atr: list[float | None] = field(default_factory=list)
    bb_upper: list[float | None] = field(default_factory=list)
    bb_lower: list[float | None] = field(default_factory=list)
    rsi: list[float | None] = field(default_factory=list)


def build_indicator_cache(rows: list[dict], cfg: "PatternFilterConfig") -> IndicatorCache:
    closes = [float(r["close"]) for r in rows]
    mid, upper, lower = bollinger(closes, cfg.bb_period, cfg.bb_std)
    return IndicatorCache(
        ema_fast=ema(closes, cfg.ema_fast),
        ema_slow=ema(closes, cfg.ema_slow),
        adx=adx(rows, cfg.adx_period),
        atr=atr(rows, cfg.atr_period),
        bb_upper=upper,
        bb_lower=lower,
        rsi=rsi(closes, cfg.rsi_period),
    )


@dataclass
class PendingPattern:
    side: str
    pattern: str
    pattern_ts: str
    pattern_epoch: float
    pattern_high: float
    pattern_low: float
    pattern_range: float
    risk_points: float = 0.0
    target_step: float = 0.0
    break_seen: bool = False


@dataclass
class PatternFilterConfig:
    trend_lookback: int = 6
    min_shadow_ratio: float = 2.0
    min_pattern_points: float = 1.5
    target_points: float = 40.0
    min_confirm_body: float = 0.5
    sl_buffer_points: float = 0.5
    # Trend-following regime
    use_ema_regime: bool = True
    ema_fast: int = 20
    ema_slow: int = 50
    use_adx_filter: bool = True
    adx_period: int = 14
    adx_min: float = 20.0
    use_donchian_filter: bool = True
    donchian_period: int = 20
    # Mean-reversion confirm
    use_bollinger_rsi: bool = True
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    rsi_oversold: float = 25.0
    rsi_overbought: float = 75.0
    # Volatility risk overlay
    use_atr_stops: bool = True
    atr_period: int = 14
    atr_stop_mult: float = 1.5
    atr_target_mult: float = 2.0
    use_adaptive_targets: bool = True
    # Session filter (UTC)
    use_session_filter: bool = True
    session_london_start: int = 7
    session_london_end: int = 10
    session_overlap_start: int = 12
    session_overlap_end: int = 16
    # Loss control (Hammer technique keeps pattern SL)
    min_overlay_votes: int = 2
    max_sl_points: float = 25.0
    min_rr_ratio: float = 1.5
    atr_max_risk_mult: float = 2.0  # skip if pattern risk > this × ATR


def _candle_parts(bar: dict) -> tuple[float, float, float, float]:
    open_ = float(bar["open"])
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    body = abs(close - open_)
    upper = high - max(open_, close)
    lower = min(open_, close) - low
    total_range = high - low
    return body, upper, lower, total_range


def is_hammer(bar: dict, *, min_shadow_ratio: float = 2.0) -> bool:
    """Classic hammer: long lower wick, small body, little/no upper wick."""
    body, upper, lower, total_range = _candle_parts(bar)
    if total_range <= 0:
        return False
    if body <= 0:
        return lower >= 0.60 * total_range and upper <= 0.10 * total_range
    # Strict hammer shape (reduces weak / doji-like losers)
    return (
        lower >= min_shadow_ratio * body
        and upper <= 0.5 * body
        and lower >= 0.50 * total_range
    )


def is_shooting_star(bar: dict, *, min_shadow_ratio: float = 2.0) -> bool:
    """Classic shooting star: long upper wick, small body, little/no lower wick."""
    body, upper, lower, total_range = _candle_parts(bar)
    if total_range <= 0:
        return False
    if body <= 0:
        return upper >= 0.60 * total_range and lower <= 0.10 * total_range
    return (
        upper >= min_shadow_ratio * body
        and lower <= 0.5 * body
        and upper >= 0.50 * total_range
    )


def _in_downtrend(rows: list[dict], index: int, lookback: int) -> bool:
    if index < lookback:
        return False
    closes = [float(rows[i]["close"]) for i in range(index - lookback, index + 1)]
    current = closes[-1]
    prior = closes[:-1]
    return current < sum(prior) / len(prior) and current <= prior[-1]


def _in_uptrend(rows: list[dict], index: int, lookback: int) -> bool:
    if index < lookback:
        return False
    closes = [float(rows[i]["close"]) for i in range(index - lookback, index + 1)]
    current = closes[-1]
    prior = closes[:-1]
    return current > sum(prior) / len(prior) and current >= prior[-1]


def pattern_config_from_params(params) -> PatternFilterConfig:
    def _bool(name: str, default: bool) -> bool:
        return bool(getattr(params, name, default))

    return PatternFilterConfig(
        trend_lookback=int(getattr(params, "trend_lookback", 6) or 6),
        min_shadow_ratio=float(getattr(params, "min_shadow_ratio", 2.0) or 2.0),
        min_pattern_points=float(getattr(params, "min_pattern_points", 1.5) or 1.5),
        target_points=float(getattr(params, "target_points", 40.0) or 40.0),
        min_confirm_body=float(getattr(params, "min_confirm_body", 0.5) or 0.5),
        sl_buffer_points=float(getattr(params, "sl_buffer_points", 0.5) or 0.5),
        use_ema_regime=_bool("use_ema_regime", True),
        ema_fast=int(getattr(params, "ema_fast", 20) or 20),
        ema_slow=int(getattr(params, "ema_slow", 50) or 50),
        use_adx_filter=_bool("use_adx_filter", True),
        adx_period=int(getattr(params, "adx_period", 14) or 14),
        adx_min=float(getattr(params, "adx_min", 20.0) or 20.0),
        use_donchian_filter=_bool("use_donchian_filter", True),
        donchian_period=int(getattr(params, "donchian_period", 20) or 20),
        use_bollinger_rsi=_bool("use_bollinger_rsi", True),
        bb_period=int(getattr(params, "bb_period", 20) or 20),
        bb_std=float(getattr(params, "bb_std", 2.0) or 2.0),
        rsi_period=int(getattr(params, "rsi_period", 14) or 14),
        rsi_oversold=float(getattr(params, "rsi_oversold", 25.0) or 25.0),
        rsi_overbought=float(getattr(params, "rsi_overbought", 75.0) or 75.0),
        use_atr_stops=_bool("use_atr_stops", True),
        atr_period=int(getattr(params, "atr_period", 14) or 14),
        atr_stop_mult=float(getattr(params, "atr_stop_mult", 1.5) or 1.5),
        atr_target_mult=float(getattr(params, "atr_target_mult", 2.0) or 2.0),
        use_adaptive_targets=_bool("use_adaptive_targets", True),
        use_session_filter=_bool("use_session_filter", True),
        session_london_start=int(getattr(params, "session_london_start", 7) or 7),
        session_london_end=int(getattr(params, "session_london_end", 10) or 10),
        session_overlap_start=int(getattr(params, "session_overlap_start", 12) or 12),
        session_overlap_end=int(getattr(params, "session_overlap_end", 16) or 16),
        min_overlay_votes=int(getattr(params, "min_overlay_votes", 2) or 2),
        max_sl_points=float(getattr(params, "max_sl_points", 25.0) or 25.0),
        min_rr_ratio=float(getattr(params, "min_rr_ratio", 1.5) or 1.5),
        atr_max_risk_mult=float(getattr(params, "atr_max_risk_mult", 2.0) or 2.0),
    )


def _session_ok(bar: dict, cfg: PatternFilterConfig) -> bool:
    if not cfg.use_session_filter:
        return True
    return in_gold_session(
        bar["timestamp"],
        london_start=cfg.session_london_start,
        london_end=cfg.session_london_end,
        overlap_start=cfg.session_overlap_start,
        overlap_end=cfg.session_overlap_end,
    )


def _adx_ok(cache: IndicatorCache, index: int, cfg: PatternFilterConfig) -> bool:
    if not cfg.use_adx_filter:
        return True
    if index >= len(cache.adx):
        return False
    current = cache.adx[index]
    if current is None:
        return False
    return current >= cfg.adx_min


def _ema_regime_ok(cache: IndicatorCache, rows: list[dict], index: int, side: str, cfg: PatternFilterConfig) -> bool:
    """Higher-TF regime: longs only above slow EMA, shorts only below (pullback structure)."""
    if not cfg.use_ema_regime:
        return True
    if index >= len(cache.ema_slow):
        return False
    s_val = cache.ema_slow[index]
    if s_val is None:
        return False
    price = float(rows[index]["close"])
    if side == "long":
        return price >= s_val * 0.998
    return price <= s_val * 1.002


def _donchian_ok(rows: list[dict], index: int, side: str, cfg: PatternFilterConfig) -> bool:
    """Prefer entries near channel extremes (pullback/breakout context)."""
    if not cfg.use_donchian_filter:
        return True
    hi, lo = donchian_prior(rows, index, cfg.donchian_period)
    if hi is None or lo is None or hi <= lo:
        return False
    mid = (hi + lo) / 2.0
    close = float(rows[index]["close"])
    low = float(rows[index]["low"])
    high = float(rows[index]["high"])
    if side == "long":
        return low <= lo + 0.35 * (hi - lo) or close >= mid
    return high >= hi - 0.35 * (hi - lo) or close <= mid


def _mean_reversion_ok(
    cache: IndicatorCache,
    rows: list[dict],
    index: int,
    side: str,
    cfg: PatternFilterConfig,
) -> bool:
    """Bollinger / RSI confirm — either outer-band touch OR RSI extreme (gold-friendly)."""
    if not cfg.use_bollinger_rsi:
        return True
    if index >= len(cache.bb_upper) or index >= len(cache.rsi):
        return False
    u, l, r = cache.bb_upper[index], cache.bb_lower[index], cache.rsi[index]
    if u is None or l is None or r is None:
        return False
    low = float(rows[index]["low"])
    high = float(rows[index]["high"])
    pad = abs(float(rows[index]["close"])) * 0.0015  # ~0.15% proximity
    if side == "long":
        band_hit = low <= l + pad
        rsi_hit = r <= cfg.rsi_oversold
        return band_hit or rsi_hit
    band_hit = high >= u - pad
    rsi_hit = r >= cfg.rsi_overbought
    return band_hit or rsi_hit


def _atr_value(cache: IndicatorCache, index: int, cfg: PatternFilterConfig) -> float | None:
    if not cfg.use_atr_stops:
        return None
    if index >= len(cache.atr):
        return None
    return cache.atr[index]


def _stop_and_target(
    side: str,
    entry_ref: float,
    pattern_stop: float,
    atr_val: float | None,
    cfg: PatternFilterConfig,
) -> tuple[float, float, float] | None:
    """Hammer technique: SL at pattern extreme. ATR only rejects oversized risk."""
    # Always use classic pattern stop (hammer low / star high) — do not widen with ATR
    stop = pattern_stop
    if side == "long":
        risk = entry_ref - stop
    else:
        risk = stop - entry_ref
    if risk <= 0:
        return None

    # Skip trades where stop is too wide (cuts large losers)
    if cfg.max_sl_points > 0 and risk > cfg.max_sl_points:
        return None
    if cfg.use_atr_stops and atr_val is not None and atr_val > 0:
        if risk > cfg.atr_max_risk_mult * atr_val:
            return None

    # Target: at least min R:R vs pattern risk; floor at target_points
    rr_step = risk * cfg.min_rr_ratio if cfg.min_rr_ratio > 0 else cfg.target_points
    if cfg.use_atr_stops and atr_val is not None and atr_val > 0 and cfg.use_adaptive_targets:
        step = max(cfg.target_points, cfg.atr_target_mult * atr_val, rr_step)
    else:
        step = max(cfg.target_points, rr_step)
    if cfg.min_rr_ratio > 0 and step / risk < cfg.min_rr_ratio:
        return None
    return stop, step, risk


def _passes_overlays(
    cache: IndicatorCache,
    rows: list[dict],
    index: int,
    side: str,
    cfg: PatternFilterConfig,
) -> bool:
    """Need at least `min_overlay_votes` of the 5 gold techniques (default 2).

    Keeps Hammer/Star as the entry; overlays only filter weak setups to cut losses.
    """
    votes: list[bool] = []
    if cfg.use_ema_regime:
        votes.append(_ema_regime_ok(cache, rows, index, side, cfg))
    if cfg.use_adx_filter:
        if index >= len(cache.adx) or cache.adx[index] is None:
            votes.append(False)
        else:
            votes.append(float(cache.adx[index]) >= cfg.adx_min)
    if cfg.use_donchian_filter:
        votes.append(_donchian_ok(rows, index, side, cfg))
    if cfg.use_bollinger_rsi:
        votes.append(_mean_reversion_ok(cache, rows, index, side, cfg))
    if cfg.use_session_filter:
        votes.append(_session_ok(rows[index], cfg))

    if not votes:
        return True
    needed = max(1, min(cfg.min_overlay_votes, len(votes)))
    return sum(1 for v in votes if v) >= needed


def detect_pattern(
    bar: dict,
    rows: list[dict],
    index: int,
    *,
    cfg: PatternFilterConfig,
    swings=None,
    cache: IndicatorCache | None = None,
) -> PendingPattern | None:
    del swings  # call-site compatibility
    total_range = float(bar["high"]) - float(bar["low"])
    if total_range < cfg.min_pattern_points:
        return None

    ind = cache or build_indicator_cache(rows[: index + 1], cfg)
    atr_val = _atr_value(ind, index, cfg)

    if is_hammer(bar, min_shadow_ratio=cfg.min_shadow_ratio) and _in_downtrend(
        rows, index, cfg.trend_lookback
    ):
        if not _passes_overlays(ind, rows, index, "long", cfg):
            return None
        entry_ref = float(bar["high"])
        pattern_stop = float(bar["low"]) - cfg.sl_buffer_points
        sized = _stop_and_target("long", entry_ref, pattern_stop, atr_val, cfg)
        if sized is None:
            return None
        stop, step, risk = sized
        return PendingPattern(
            side="long",
            pattern="hammer",
            pattern_ts=bar["timestamp"],
            pattern_epoch=epoch_of(bar["timestamp"]),
            pattern_high=float(bar["high"]),
            pattern_low=stop,
            pattern_range=total_range,
            risk_points=risk,
            target_step=step,
        )

    if is_shooting_star(bar, min_shadow_ratio=cfg.min_shadow_ratio) and _in_uptrend(
        rows, index, cfg.trend_lookback
    ):
        if not _passes_overlays(ind, rows, index, "short", cfg):
            return None
        entry_ref = float(bar["low"])
        pattern_stop = float(bar["high"]) + cfg.sl_buffer_points
        sized = _stop_and_target("short", entry_ref, pattern_stop, atr_val, cfg)
        if sized is None:
            return None
        stop, step, risk = sized
        return PendingPattern(
            side="short",
            pattern="shooting_star",
            pattern_ts=bar["timestamp"],
            pattern_epoch=epoch_of(bar["timestamp"]),
            pattern_high=stop,
            pattern_low=float(bar["low"]),
            pattern_range=total_range,
            risk_points=risk,
            target_step=step,
        )
    return None


def pattern_invalidated(pending: PendingPattern, bar: dict) -> bool:
    close = float(bar["close"])
    if pending.side == "long":
        return close < pending.pattern_low
    return close > pending.pattern_high


def _confirm_body_ok(bar: dict, min_body: float) -> bool:
    return abs(float(bar["close"]) - float(bar["open"])) >= min_body


def _build_signal(pending: PendingPattern, bar: dict, entry: float, cfg: PatternFilterConfig) -> EntrySignal | None:
    if pending.side == "long":
        stop = pending.pattern_low
        target = entry + pending.target_step
        if stop >= entry:
            return None
        return EntrySignal(
            side="long",
            entry_ts=bar["timestamp"],
            entry_price=entry,
            stop_loss=stop,
            target=target,
            swing_price=pending.pattern_high,
            sweep_extreme=pending.pattern_low,
            grab_ts=pending.pattern_ts,
            first_high=pending.pattern_high,
            first_low=pending.pattern_low,
        )

    stop = pending.pattern_high
    target = entry - pending.target_step
    if stop <= entry:
        return None
    return EntrySignal(
        side="short",
        entry_ts=bar["timestamp"],
        entry_price=entry,
        stop_loss=stop,
        target=target,
        swing_price=pending.pattern_low,
        sweep_extreme=pending.pattern_high,
        grab_ts=pending.pattern_ts,
        first_high=pending.pattern_high,
        first_low=pending.pattern_low,
    )


def confirm_pattern_entry(
    pending: PendingPattern,
    bar: dict,
    *,
    cfg: PatternFilterConfig,
) -> EntrySignal | None:
    """Enter on 1m close through the pattern extreme after a break."""
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])

    if pending.side == "long":
        if high > pending.pattern_high:
            pending.break_seen = True
        if not pending.break_seen:
            return None
        if not is_green(bar) or close <= pending.pattern_high:
            return None
        if not _confirm_body_ok(bar, cfg.min_confirm_body):
            return None
        return _build_signal(pending, bar, close, cfg)

    if low < pending.pattern_low:
        pending.break_seen = True
    if not pending.break_seen:
        return None
    if not is_red(bar) or close >= pending.pattern_low:
        return None
    if not _confirm_body_ok(bar, cfg.min_confirm_body):
        return None
    return _build_signal(pending, bar, close, cfg)
