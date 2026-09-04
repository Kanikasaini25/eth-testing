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
      "If the rejection candle is red, it is the first red candle; enter short only when the next red candle breaks the first red candle low.",
      "LONG setup: price must first reach the lower liquidity line (previous day low zone).",
      "LONG entry: after the previous day low is broken/swept, wait for a bullish 1m rejection candle; its close may remain below the liquidity line.",
      "If the rejection candle is green, it is the first green candle; enter long only when the next green candle breaks the first green candle high.",
      "After a profitable trade, allow same-direction re-entry only after an opposite-color pullback and a new two-candle confirmation; do not require another liquidity-line break.",
      "Trade throughout the full UTC day (00:00–24:00 UTC).",
      "If price is between the two lines, there is no trade."
    ],
    "exit_rules": [
      "Risk R is the absolute distance from entry to the initial stop.",
      "At +2% profit, keep the initial SL unchanged.",
      "At +3% profit, move SL to +2% profit.",
      "At +4% profit, move SL to +3% profit.",
      "At +5% profit, close the entire position."
    ],
    "risk_rules": [
      "Stop loss for LONG: below the first green candle wick low.",
      "Stop loss for SHORT: above the first red candle wick high.",
      "Always enter with fixed 100 lots on every trade.",
      "After 2 full stop losses in one UTC day, stop trading for that day.",
      "After a full stop loss, another entry from the same line is allowed until 3 daily attempts are reached.",
      "After TP1 or TP2, the full position remains open while the stop locks the achieved R level.",
      "Never take more than 3 trades in one sequence.",
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
      "use_daily_trend_filter": false,
      "use_session_filter": true,
      "session_start_hour_delta": 0,
      "session_end_hour_delta": 0,
      "min_signal_body_ratio": 0.0,
      "min_signal_range_points": 0.0,
      "position_lots": 100,
      "risk_reward_ratio": 2,
      "profit_milestones_pct": [
        2,
        3,
        4,
        5
      ],
      "starting_wallet_usd": 10000,
      "stop_loss_mode": "first_confirmation_candle_wick",
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

_Note: LQDTY liquidity rules use 1D setup + 1M entry in the video. The backtest below is a daily ETH approximation only._

| Technique | Trades | Win Rate | Strategy Return | Buy & Hold | Max Drawdown | Verdict |
|-----------|--------|----------|-----------------|------------|--------------|---------|
| LQDTY Liquidity Strategy | 36 | 16.67% | 2.81% | 34.55% | 0.68% | Mixed |

## Backtest Mode

- **LQDTY Liquidity Strategy:** `eth_100lots_r_multiple`

## Rule Compliance Check

### LQDTY Liquidity Strategy
- Uses Previous Day High Low Lines: **Yes**
- Uses 1M Candle Confirmation: **Yes**
- Supports Long And Short: **Yes**
- Uses First Confirmation Candle Wick Stop Loss: **Yes**
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
- Uses Daily Trend Filter: **No**
- Uses Delta India Session Filter: **Yes**
- Simulates Trading Fees: **Yes**


## Trade Details

### LQDTY Liquidity Strategy

| Entry | Exit | Entry Price | Exit Price | Points | P/L ($) | Reason |
|-------|------|-------------|------------|--------|---------|--------|
| 2026-08-02 02:09 UTC | 2026-08-02 02:19 UTC | 1871.45 | 1881.75 | -10.3 | $-12.18 | stop_loss |
| 2026-08-02 02:22 UTC | 2026-08-02 04:56 UTC | 1879.3 | 1881.0 | -1.7 | $-3.58 | stop_loss |
| 2026-08-03 07:19 UTC | 2026-08-03 08:18 UTC | 1841.25 | 1839.2 | -2.05 | $-3.89 | stop_loss |
| 2026-08-03 08:23 UTC | 2026-08-03 08:30 UTC | 1832.55 | 1829.7 | -2.85 | $-4.68 | stop_loss |
| 2026-08-05 12:31 UTC | 2026-08-05 16:21 UTC | 1880.25 | 1884.95 | -4.7 | $-6.58 | stop_loss |
| 2026-08-05 16:31 UTC | 2026-08-05 17:00 UTC | 1893.25 | 1896.75 | -3.5 | $-5.40 | stop_loss |
| 2026-08-07 11:24 UTC | 2026-08-07 12:07 UTC | 1918.55 | 1920.3 | -1.75 | $-3.67 | stop_loss |
| 2026-08-07 12:13 UTC | 2026-08-07 12:30 UTC | 1933.35 | 1937.0 | -3.65 | $-5.59 | stop_loss |
| 2026-08-09 15:00 UTC | 2026-08-09 15:10 UTC | 1924.35 | 1926.0 | -1.65 | $-3.58 | stop_loss |
| 2026-08-09 15:12 UTC | 2026-08-09 15:15 UTC | 1925.75 | 1926.3 | -0.55 | $-2.48 | stop_loss |
| 2026-08-10 00:46 UTC | 2026-08-10 12:58 UTC | 1907.55 | 1905.65 | -1.9 | $-3.81 | stop_loss |
| 2026-08-10 13:01 UTC | 2026-08-10 13:34 UTC | 1906.15 | 1904.0 | -2.15 | $-4.06 | stop_loss |
| 2026-08-11 15:43 UTC | 2026-08-12 14:02 UTC | 1857.05 | 1894.19 | 37.14 | $+35.27 | stop_at_2pct |
| 2026-08-12 14:08 UTC | 2026-08-12 14:31 UTC | 1891.65 | 1889.5 | -2.15 | $-4.04 | stop_loss |
| 2026-08-13 16:44 UTC | 2026-08-19 14:54 UTC | 1865.6 | 1958.88 | 93.28 | $+91.37 | take_profit_5pct |
| 2026-08-19 15:03 UTC | 2026-08-19 15:27 UTC | 1974.15 | 2072.86 | 98.71 | $+96.68 | take_profit_5pct |
| 2026-08-19 15:32 UTC | 2026-08-19 20:50 UTC | 2069.05 | 2172.5 | 103.45 | $+101.33 | take_profit_5pct |
| 2026-08-19 20:59 UTC | 2026-08-19 21:06 UTC | 2215.9 | 2260.22 | 44.32 | $+42.08 | stop_at_2pct |
| 2026-08-20 15:55 UTC | 2026-08-20 16:41 UTC | 2329.45 | 2337.3 | -7.85 | $-10.18 | stop_loss |
| 2026-08-20 16:45 UTC | 2026-08-21 01:18 UTC | 2345.8 | 2356.65 | -10.85 | $-13.20 | stop_loss |
| 2026-08-21 01:36 UTC | 2026-08-21 01:40 UTC | 2358.2 | 2360.55 | -2.35 | $-4.71 | stop_loss |
| 2026-08-23 04:50 UTC | 2026-08-23 05:08 UTC | 2378.2 | 2371.2 | -7.0 | $-9.37 | stop_loss |
| 2026-08-23 05:10 UTC | 2026-08-23 05:16 UTC | 2372.75 | 2362.25 | -10.5 | $-12.87 | stop_loss |
| 2026-08-24 11:39 UTC | 2026-08-24 11:40 UTC | 2492.35 | 2497.15 | -4.8 | $-7.29 | stop_loss |
| 2026-08-24 11:46 UTC | 2026-08-24 12:51 UTC | 2498.85 | 2508.65 | -9.8 | $-12.30 | stop_loss |
| 2026-08-25 21:11 UTC | 2026-08-27 08:30 UTC | 2423.65 | 2544.83 | 121.18 | $+118.70 | take_profit_5pct |
| 2026-08-27 08:42 UTC | 2026-08-27 08:55 UTC | 2535.05 | 2528.65 | -6.4 | $-8.93 | stop_loss |
| 2026-08-27 08:59 UTC | 2026-08-27 09:08 UTC | 2529.8 | 2531.65 | -1.85 | $-4.38 | stop_loss |
| 2026-08-28 04:11 UTC | 2026-08-28 14:06 UTC | 2484.15 | 2479.85 | -4.3 | $-6.78 | stop_loss |
| 2026-08-28 14:08 UTC | 2026-08-28 14:11 UTC | 2485.6 | 2480.05 | -5.55 | $-8.03 | stop_loss |
| 2026-08-30 00:33 UTC | 2026-08-30 00:36 UTC | 2459.8 | 2461.2 | -1.4 | $-3.86 | stop_loss |
| 2026-08-30 00:38 UTC | 2026-08-30 12:05 UTC | 2462.45 | 2464.4 | -1.95 | $-4.41 | stop_loss |
| 2026-09-01 18:47 UTC | 2026-09-02 09:23 UTC | 2387.3 | 2381.7 | -5.6 | $-7.98 | stop_loss |
| 2026-09-02 09:34 UTC | 2026-09-02 09:44 UTC | 2374.45 | 2368.0 | -6.45 | $-8.82 | stop_loss |
| 2026-09-03 13:35 UTC | 2026-09-03 13:40 UTC | 2425.15 | 2432.35 | -7.2 | $-9.63 | stop_loss |
| 2026-09-03 13:46 UTC | 2026-09-03 14:11 UTC | 2430.05 | 2435.5 | -5.45 | $-7.88 | stop_loss |

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
If the rejection candle is red, it is the first red candle; enter short only when the next red candle breaks the first red candle low.
LONG setup: price must first reach the lower liquidity line (previous day low zone).
LONG entry: after the previous day low is broken/swept, wait for a bullish 1m rejection candle; its close may remain below the liquidity line.
If the rejection candle is green, it is the first green candle; enter long only when the next green candle breaks the first green candle high....

---
_For research only. Past performance does not guarantee future results._