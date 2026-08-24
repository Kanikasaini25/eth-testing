from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VolumeProfileLevels:
    poc: float
    val: float
    vah: float
    session_open: float
    session_close: float
    session_high: float
    session_low: float
    total_volume: float


def _bin_start(price: float, bin_size: float) -> float:
    return (price // bin_size) * bin_size


def _distribute_volume(bars: list[dict], bin_size: float) -> dict[float, float]:
    volumes: dict[float, float] = {}
    for bar in bars:
        low = float(bar["low"])
        high = float(bar["high"])
        volume = float(bar.get("volume") or 0.0)
        if volume <= 0:
            continue
        start = _bin_start(low, bin_size)
        end = _bin_start(high, bin_size)
        covered: list[float] = []
        level = start
        while level <= end + (bin_size / 2.0):
            covered.append(level)
            level += bin_size
        if not covered:
            covered = [start]
        share = volume / len(covered)
        for bin_price in covered:
            volumes[bin_price] = volumes.get(bin_price, 0.0) + share
    return volumes


def _expand_value_area(
    bins: list[float],
    volumes: dict[float, float],
    poc_bin: float,
    total_volume: float,
    value_area_pct: float,
) -> tuple[float, float]:
    poc_index = bins.index(poc_bin)
    low_index = poc_index
    high_index = poc_index
    captured = volumes[poc_bin]
    target = total_volume * value_area_pct
    while captured < target and (low_index > 0 or high_index < len(bins) - 1):
        below = volumes[bins[low_index - 1]] if low_index > 0 else -1.0
        above = volumes[bins[high_index + 1]] if high_index < len(bins) - 1 else -1.0
        if above > below:
            high_index += 1
            captured += volumes[bins[high_index]]
        elif below > above:
            low_index -= 1
            captured += volumes[bins[low_index]]
        else:
            if low_index > 0:
                low_index -= 1
                captured += volumes[bins[low_index]]
            if high_index < len(bins) - 1 and captured < target:
                high_index += 1
                captured += volumes[bins[high_index]]
    return bins[low_index], bins[high_index]


def build_fixed_range_profile(
    bars: list[dict],
    *,
    bin_size: float = 1.0,
    value_area_pct: float = 0.70,
) -> VolumeProfileLevels | None:
    """POC / VAL / VAH from a previous trading day's complete 15m range."""
    if not bars or bin_size <= 0:
        return None
    volumes = _distribute_volume(bars, bin_size)
    if not volumes:
        return None
    bins = sorted(volumes)
    poc_bin = max(bins, key=lambda price: (volumes[price], -price))
    total_volume = sum(volumes.values())
    val_bin, vah_bin = _expand_value_area(
        bins, volumes, poc_bin, total_volume, value_area_pct
    )
    session_open = float(bars[0]["open"])
    session_close = float(bars[-1]["close"])
    return VolumeProfileLevels(
        poc=poc_bin + (bin_size / 2.0),
        val=val_bin,
        vah=vah_bin + bin_size,
        session_open=session_open,
        session_close=session_close,
        session_high=max(float(bar["high"]) for bar in bars),
        session_low=min(float(bar["low"]) for bar in bars),
        total_volume=total_volume,
    )
