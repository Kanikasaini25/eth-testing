# Strategy Backtest Report

## Video
- URL: https://www.youtube.com/watch?v=wI9b968AvW8&t=19s

## Market Data
- API: https://api.india.delta.exchange
- Symbol: ETHUSD
- Timeframe: 1d

## Extracted Techniques
```json
[
  {
    "name": "LQDTY Liquidity Strategy",
    "strategy_type": "liquidity",
    "setup_rules": [
      "Core principle: LQDTY (Liquidity) — trade where retail stop losses cluster.",
      "Use 1 Day timeframe on the chart.",
      "Take the previous completed day candle (skip the running/current day candle).",
      "Draw two horizontal lines: one at the previous day high and one at the previous day low.",
      "These two lines are the liquidity levels for the next session.",
      "After drawing the lines, switch to the 1 minute timeframe for execution.",
      "Video demonstrates on Gold; the same logic can be adapted to ETH, BTC, or indices after backtesting.",
      "Do not take a trade if price stays in the middle and never reaches a liquidity line.",
      "Set alerts on your broker or TradingView when price approaches a liquidity line."
    ],
    "entry_rules": [
      "Every entry is exactly 100 lots — fixed size, no scaling.",
      "SHORT setup: price must first reach the upper liquidity line (previous day high zone).",
      "SHORT entry: after the previous day high is broken/swept, wait for a bearish 1m rejection candle; its close may remain above the liquidity line.",
      "If the rejection candle is red, it is the first red candle; enter short only when the next red candle breaks the first red candle low (no need to close below the rally-green low).",
      "LONG setup: price must first reach the lower liquidity line (previous day low zone).",
      "LONG entry: after the previous day low is broken/swept, wait for a bullish 1m rejection candle; its close may remain below the liquidity line.",
      "If the rejection candle is green, it is the first green candle; enter long only when the next green candle breaks the first green candle high (no need to close above the dump-red high).",
      "Fresh lower-low / higher-high retest (require_fresh_extreme_retest): below the previous day low, the first green candle must come within 3 candles of a new day low (price broke the last lower low once) and its low must retest that new low within 1 point; then apply the two-green-candle formula. Green candles in the middle of the range are ignored. Mirror for shorts above the previous day high.",
      "Trend guard (use_trend_structure_filter): if price keeps making higher highs after breaking the previous day high, do not short on the first two red candles; wait for a close below the last higher low, a retest of that level, then apply the two-red-candle formula. Mirror for longs (lower lows below previous day low -> close above last lower high -> retest -> two green candles).",
      "After a profitable trade, allow same-direction re-entry only after an opposite-color pullback and a new two-candle confirmation; do not require another liquidity-line break.",
      "Order-flow filter: after the sweep, buyers must be dominant for LONG (or sellers for SHORT) before the 2-candle confirmation is accepted.",
      "Re-check buyer/seller dominance on the confirmation candles and again on the last 30 seconds / last 1m bar before entry; skip if the opposite side is still stronger.",
      "Trade throughout the full UTC day (00:00–24:00 UTC).",
      "If price is between the two lines, there is no trade."
    ],
    "exit_rules": [
      "Risk R is the absolute distance from entry to the initial stop.",
      "For all SL sizes (max SL 7 points): targets are 4R, 6R, 8R, 10R (at 6R move SL to 4R; at 8R move SL to 6R; at 10R close)."
    ],
    "risk_rules": [
      "Stop loss for LONG: below the latest rejection wick at the sweep low (dump/hammer wick), not the confirmation candle.",
      "Stop loss for SHORT: above the latest rejection wick at the sweep high (rally wick), not the confirmation candle.",
      "Always enter with fixed 100 lots on every trade.",
      "After 2 full stop losses in one UTC day, stop trading for that day.",
      "After a full stop loss, another entry from the same line is allowed until 3 daily attempts are reached.",
      "After TP1 or TP2, the full position remains open while the stop locks the achieved R level.",
      "Never take more than 3 trades in one sequence.",
      "If the confirmation candle breaks the signal entry level and also takes out the signal stop wick, skip the trade (no entry, no wait for a third candle).",
      "If the initial SL is more than 7 points from entry, use the 2nd dump-red (long) or 2nd rally-green (short) wick; if it is still wider than 7 points, skip the trade.",
      "Backtest on ETH futures (e.g. ETHUSD on Delta Exchange)."
    ],
    "parameters": {
      "setup_timeframe": "1d",
      "entry_timeframe": "1m",
      "lines_from": "previous_day_high_and_low",
      "instrument": "ETHUSD",
      "max_full_stop_losses_per_session": 2,
      "max_trades_per_sequence": 3,
      "max_entries_per_liquidity_line_per_day": 3,
      "entry_on_next_candle": true,
      "require_close_beyond_signal": false,
      "require_liquidity_sweep": true,
      "require_two_consecutive_confirmation_candles": true,
      "skip_if_confirmation_hits_signal_stop": true,
      "require_break_opposing_candle": false,
      "opposing_candle_lookback_bars": 60,
      "require_fresh_extreme_retest": true,
      "fresh_extreme_window_bars": 3,
      "fresh_extreme_tolerance_points": 1.0,
      "use_trend_structure_filter": false,
      "structure_pivot_bars": 10,
      "structure_min_trend_swings": 3,
      "structure_retest_tolerance_points": 1.0,
      "structure_retest_window_bars": 5,
      "structure_lookback_bars": 240,
      "use_order_flow_filter": true,
      "order_flow_min_dominance": 0.6,
      "order_flow_min_ratio": 1.5,
      "order_flow_sweep_lookback_bars": 2,
      "order_flow_confirm_bars": 2,
      "order_flow_entry_bars": 1,
      "order_flow_entry_window_seconds": 30,
      "order_flow_require_price_align": true,
      "order_flow_require_sweep_reversal": true,
      "use_daily_trend_filter": false,
      "use_session_filter": true,
      "session_start_hour_delta": 0,
      "session_end_hour_delta": 0,
      "min_signal_body_ratio": 0.0,
      "min_signal_range_points": 0.0,
      "position_lots": 100,
      "risk_reward_ratio": 2,
      "profit_milestones_r": [
        4,
        6,
        8,
        10
      ],
      "starting_wallet_usd": 10000,
      "stop_loss_mode": "latest_rejection_wick",
      "max_sl_points": 7,
      "swing_lookback_days": 20,
      "runner_swing_lookback_days": 60,
      "fee_pct_per_side": 0.05,
      "platform_fee_pct_per_side": 0.0
    },
    "source_quotes": [
      "। सबसे बेस्ट क्या है? जो मैं बता रहा हूं आपको, एक वन डे का टाइम फ्रेम चूज़ करो। अब जैसे ही तुम वन डे का टाइम फ्रेम चूज़ करोगे, मैं डिलीट कर देता हूं। एक काम करता हूं ना, हां, डिलीट ही कर देता हूं सारा चीज़। ठीक है"
    ]
  }
]
```

## Backtest Results

_Note: LQDTY liquidity rules use 1D setup + 1M entry. The backtest below is a daily ETH approximation only._

| Technique | Trades | Win Rate | Strategy Return | Buy & Hold | Max Drawdown | Verdict |
|-----------|--------|----------|-----------------|------------|--------------|---------|
| LQDTY Liquidity Strategy | 26 | 38.46% | 1.07% | 8.4% | 0.54% | Mixed |

## Backtest Mode

- **LQDTY Liquidity Strategy:** `eth_100lots_r_multiple`

## Rule Compliance Check

### LQDTY Liquidity Strategy
- Uses Previous Day High Low Lines: **Yes**
- Uses 1M Candle Confirmation: **Yes**
- Supports Long And Short: **Yes**
- Uses Latest Rejection Wick Stop Loss: **Yes**
- Tightens Wide Stop With Second Wick: **Yes**
- Entry On Next Candle: **Yes**
- Requires Close Beyond Signal: **No**
- Requires Two Consecutive Confirmation Candles: **Yes**
- Uses Risk From Wick Distance: **Yes**
- Uses 1 To 2 Risk Reward: **Yes**
- Fixed 100 Lot Entry: **Yes**
- Keeps Full Position At Tp1: **Yes**
- Moves Stop To 2R At Tp1: **Yes**
- Moves Stop To 3R At Tp2: **Yes**
- Closes Full Position At Tp3: **Yes**
- Limits Max Trades Per Session: **Yes**
- Limits Max Full Stop Losses: **Yes**
- One Attempt Per Liquidity Line Per Day: **No**
- Blocks Line After Full Stop Loss: **No**
- Skips Middle Zone Without Touch: **Yes**
- Instrument Eth Futures: **Yes**
- Requires Liquidity Sweep Rejection: **Yes**
- Skips If Confirmation Hits Signal Stop: **Yes**
- Uses Daily Trend Filter: **No**
- Uses Delta India Session Filter: **Yes**
- Simulates Trading Fees: **Yes**
- Uses Order Flow Filter: **Yes**
- Requires Break Opposing Candle: **No**
- Waits For Choch Retest In Trend: **No**
- Requires Fresh Extreme Retest: **Yes**


## Trade Details

### LQDTY Liquidity Strategy

| Entry | Exit | Entry Price | Exit Price | Buyers | Sellers | Points | P/L ($) | Reason |
|-------|------|-------------|------------|--------|---------|--------|---------|--------|
| 2026-09-02 09:47 UTC | 2026-09-02 10:31 UTC | 2369.0 | 2365.35 | 136762 | 23993 | -3.65 | $-6.02 | stop_loss |
| 2026-09-03 13:46 UTC | 2026-09-03 14:11 UTC | 2430.05 | 2435.5 | 23624 | 153161 | -5.45 | $-7.88 | stop_loss |
| 2026-09-03 14:19 UTC | 2026-09-03 14:23 UTC | 2437.4 | 2443.9 | 14149 | 97725 | -6.5 | $-8.94 | stop_loss |
| 2026-09-06 01:15 UTC | 2026-09-06 01:36 UTC | 2495.9 | 2498.7 | 1598 | 26574 | -2.8 | $-5.30 | stop_loss |
| 2026-09-06 01:41 UTC | 2026-09-06 02:00 UTC | 2504.3 | 2507.0 | 6605 | 50556 | -2.7 | $-5.21 | stop_loss |
| 2026-09-13 08:41 UTC | 2026-09-13 09:24 UTC | 2492.8 | 2486.6 | 165846 | 12644 | -6.2 | $-8.69 | stop_loss |
| 2026-09-13 09:35 UTC | 2026-09-13 10:57 UTC | 2474.9 | 2469.35 | 137250 | 32403 | -5.55 | $-8.02 | stop_loss |
| 2026-09-17 06:48 UTC | 2026-09-17 07:06 UTC | 2444.45 | 2445.8 | 7841 | 44667 | -1.35 | $-3.80 | stop_loss |
| 2026-09-17 07:12 UTC | 2026-09-17 11:58 UTC | 2450.45 | 2438.45 | 11317 | 65472 | 12.0 | $+9.56 | stop_at_4R |
| 2026-09-17 12:36 UTC | 2026-09-17 13:47 UTC | 2468.1 | 2443.8 | 0 | 66902 | 24.3 | $+21.84 | stop_at_6R |
| 2026-09-18 03:19 UTC | 2026-09-18 05:08 UTC | 2478.55 | 2484.85 | 26578 | 88827 | -6.3 | $-8.78 | stop_loss |
| 2026-09-18 07:08 UTC | 2026-09-18 07:21 UTC | 2491.3 | 2495.0 | 2908 | 67999 | -3.7 | $-6.19 | stop_loss |
| 2026-09-21 16:33 UTC | 2026-09-21 19:18 UTC | 2762.05 | 2768.15 | 41216 | 106445 | -6.1 | $-8.87 | stop_loss |
| 2026-09-21 20:30 UTC | 2026-09-21 22:17 UTC | 2801.65 | 2781.85 | 14043 | 112837 | 19.8 | $+17.01 | stop_at_4R |
| 2026-09-21 22:39 UTC | 2026-09-21 23:03 UTC | 2778.9 | 2783.05 | 765 | 4514 | -4.15 | $-6.93 | stop_loss |
| 2026-09-23 04:29 UTC | 2026-09-23 07:35 UTC | 2783.7 | 2742.2 | 473 | 72597 | 41.5 | $+38.74 | take_profit_10R |
| 2026-09-23 08:03 UTC | 2026-09-23 13:37 UTC | 2745.15 | 2719.75 | 1129 | 35197 | 25.4 | $+22.67 | stop_at_4R |
| 2026-09-23 13:42 UTC | 2026-09-23 14:10 UTC | 2719.65 | 2685.65 | 6566 | 77425 | 34.0 | $+31.30 | take_profit_10R |
| 2026-09-25 11:16 UTC | 2026-09-25 12:24 UTC | 2737.0 | 2705.2 | 34174 | 124933 | 31.8 | $+29.08 | stop_at_6R |
| 2026-09-25 13:00 UTC | 2026-09-25 14:16 UTC | 2715.95 | 2689.95 | 3485 | 78889 | 26.0 | $+23.30 | stop_at_4R |
| 2026-09-25 14:40 UTC | 2026-09-27 01:51 UTC | 2693.85 | 2700.25 | 0 | 73319 | -6.4 | $-9.10 | stop_loss |
| 2026-09-27 08:35 UTC | 2026-09-27 18:21 UTC | 2718.0 | 2695.2 | 5257 | 29352 | 22.8 | $+20.09 | stop_at_6R |
| 2026-09-27 18:31 UTC | 2026-09-27 18:44 UTC | 2694.75 | 2696.7 | 2086 | 11729 | -1.95 | $-4.65 | stop_loss |
| 2026-09-28 01:07 UTC | 2026-09-28 01:15 UTC | 2671.5 | 2665.5 | 89324 | 10914 | -6.0 | $-8.67 | stop_loss |
| 2026-09-28 05:40 UTC | 2026-09-28 05:51 UTC | 2636.65 | 2647.05 | 54994 | 14533 | 10.4 | $+7.76 | stop_at_4R |
| 2026-09-28 06:42 UTC | 2026-09-28 07:23 UTC | 2649.6 | 2645.0 | 21780 | 3782 | -4.6 | $-7.25 | stop_loss |

## Transcript Excerpt

LQDTY Liquidity Strategy
Core principle: LQDTY (Liquidity) — trade where retail stop losses cluster.
Use 1 Day timeframe on the chart.
Take the previous completed day candle (skip the running/current day candle).
Draw two horizontal lines: one at the previous day high and one at the previous day low.
These two lines are the liquidity levels for the next session.
After drawing the lines, switch to the 1 minute timeframe for execution.
Video demonstrates on Gold; the same logic can be adapted to ETH, BTC, or indices after backtesting.
Do not take a trade if price stays in the middle and never reaches a liquidity line.
Set alerts on your broker or TradingView when price approaches a liquidity line.
Every entry is exactly 100 lots — fixed size, no scaling.
SHORT setup: price must first reach the upper liquidity line (previous day high zone).
SHORT entry: after the previous day high is broken/swept, wait for a bearish 1m rejection candle; its close may remain above the liquidity line.
If the rejection candle is red, it is the first red candle; enter short only when the next red candle breaks the first red candle low (no need to close below the rally-green low).
LONG setup: price must first reach the lower liquidity line (previous day low zone).
LONG entry: after the previous day low is broken/swept, wait for a bullish 1m rejection candle; its close may remain below the liquidity line.
If the rejection candle is green, it is the first green candle; enter long only when the next gre...

---
_For research only. Past performance does not guarantee future results._