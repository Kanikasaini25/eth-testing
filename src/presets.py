"""The tuned parameter set for the 15m liquidity grab strategy.

Produced by scripts/optimize.py: a coordinate search over 180 days of India-live ETHUSD
candles, scored across six 30-day folds so the config has to work in more than one market
regime, then stress-tested against worse fees in scripts/stress.py.

Headline numbers are the full 180-day window at 100 lots with Delta India costs
(taker 0.05%, maker 0.02%, scalper offer on).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.backtest import BacktestParams

STRATEGY = BacktestParams(
    # cost assumptions the headline numbers were measured under
    fee_pct_per_side=0.05,
    fee_maker_pct=0.02,
    maker_on_take_profit=True,
    maker_on_entry=False,
    scalper_offer=True,
    gst_pct=0.0,
    slippage_points=0.0,
    # entry
    min_sweep_points=1.0,
    require_close_back=False,
    require_reclaim=True,
    min_confirm_body=1.0,
    require_close_break=False,
    one_shot_confirm=False,
    swing_left=4,
    swing_right=2,
    swing_lookback=48,
    confirm_timeout_minutes=120,
    # exit
    target_points=10.0,
    partial_exit_pct=0.0,
    runner_target_points=30.0,
    breakeven_points=0.0,
    max_hold_minutes=0.0,
    # risk
    use_stop_loss=True,
    sl_buffer_points=0.5,
    max_sl_points=35.0,
)


@dataclass(frozen=True)
class StrategyStats:
    """Measured on 180 days of India-live ETHUSD, 100 lots, 6/6 folds profitable."""

    setups: int = 667
    win_rate: float = 0.657
    net_pnl: float = 1292.99
    gross_pnl: float = 2238.60
    total_fees: float = 945.61
    max_drawdown: float = 83.63
    profit_factor: float = 1.51
    folds_profitable: int = 6
    folds: int = 6
    worst_case_pnl: float = -75.15


STATS = StrategyStats()

SUMMARY = (
    "Takes any 1-point sweep of a 15-minute swing, so it trades roughly 4x a day. "
    "Every 30-day fold in the 180-day sample was profitable, between +$184 and +$287."
)
