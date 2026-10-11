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
      "If the rejection candle is red, it is the first red candle; enter short only when the next red candle breaks the first red candle low AND closes below the rally-green low (the green that made the swing high).",
      "LONG setup: price must first reach the lower liquidity line (previous day low zone).",
      "LONG entry: after the previous day low is broken/swept, wait for a bullish 1m rejection candle; its close may remain below the liquidity line.",
      "If the rejection candle is green, it is the first green candle; enter long only when the next green candle breaks the first green candle high AND closes above the dump-red high (the red that made the swing low). Do not enter while price is still chopping inside that dump.",
      "After a profitable trade, allow same-direction re-entry only after an opposite-color pullback and a new two-candle confirmation; do not require another liquidity-line break.",
      "Order-flow filter: after the sweep, buyers must be dominant for LONG (or sellers for SHORT) before the 2-candle confirmation is accepted.",
      "Re-check buyer/seller dominance on the confirmation candles and again on the last 30 seconds / last 1m bar before entry; skip if the opposite side is still stronger.",
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
      "Stop loss for LONG: below the latest rejection wick at the sweep low (dump/hammer wick), not the confirmation candle.",
      "Stop loss for SHORT: above the latest rejection wick at the sweep high (rally wick), not the confirmation candle.",
      "Always enter with fixed 100 lots on every trade.",
      "After 2 full stop losses in one UTC day, stop trading for that day.",
      "After a full stop loss, another entry from the same line is allowed until 3 daily attempts are reached.",
      "After TP1 or TP2, the full position remains open while the stop locks the achieved R level.",
      "Never take more than 3 trades in one sequence.",
      "If the confirmation candle breaks the signal entry level and also takes out the signal stop wick, skip the trade (no entry, no wait for a third candle).",
      "If the initial SL is more than 15 points from entry, use the 2nd dump-red (long) or 2nd rally-green (short) wick; if it is still wider than 15 points, skip the trade.",
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
      "require_break_opposing_candle": true,
      "opposing_candle_lookback_bars": 60,
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
      "profit_milestones_pct": [
        2,
        3,
        4,
        5
      ],
      "starting_wallet_usd": 10000,
      "stop_loss_mode": "latest_rejection_wick",
      "max_sl_points": 15,
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
| LQDTY Liquidity Strategy | 25 | 32.0% | 2.4% | 28.43% | 0.75% | Mixed |

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
- Requires Break Opposing Candle: **Yes**


## Trade Details

### LQDTY Liquidity Strategy

| Entry | Exit | Entry Price | Exit Price | Buyers | Sellers | Points | P/L ($) | Reason |
|-------|------|-------------|------------|--------|---------|--------|---------|--------|
| 2026-08-02 02:29 UTC | 2026-08-02 18:41 UTC | 1875.0 | 1883.3 | 5152 | 21739 | -8.3 | $-10.18 | stop_loss |
| 2026-08-02 18:50 UTC | 2026-08-02 21:05 UTC | 1875.35 | 1886.0 | 23450 | 59182 | -10.65 | $-12.53 | stop_loss |
| 2026-08-03 07:23 UTC | 2026-08-03 08:18 UTC | 1843.2 | 1839.2 | 35968 | 0 | -4.0 | $-5.84 | stop_loss |
| 2026-08-03 08:36 UTC | 2026-08-05 18:15 UTC | 1831.7 | 1923.29 | 67538 | 608 | 91.59 | $+89.71 | take_profit_5pct |
| 2026-08-05 18:26 UTC | 2026-08-07 12:08 UTC | 1918.4 | 1926.55 | 12845 | 57574 | -8.15 | $-10.07 | stop_loss |
| 2026-08-07 12:13 UTC | 2026-08-07 12:30 UTC | 1932.6 | 1937.25 | 54456 | 114419 | -4.65 | $-6.58 | stop_loss |
| 2026-08-09 22:23 UTC | 2026-08-11 11:02 UTC | 1930.35 | 1891.74 | 1397 | 21248 | 38.61 | $+36.70 | stop_at_2pct |
| 2026-08-11 15:50 UTC | 2026-08-12 14:01 UTC | 1859.0 | 1896.18 | 70614 | 11319 | 37.18 | $+35.30 | stop_at_2pct |
| 2026-08-12 14:20 UTC | 2026-08-17 06:48 UTC | 1895.55 | 1908.7 | 27168 | 75941 | -13.15 | $-15.05 | stop_loss |
| 2026-08-17 07:15 UTC | 2026-08-17 14:52 UTC | 1903.9 | 1909.8 | 364 | 13641 | -5.9 | $-7.81 | stop_loss |
| 2026-08-18 23:29 UTC | 2026-08-18 23:34 UTC | 1918.2 | 1918.7 | 0 | 12065 | -0.5 | $-2.42 | stop_loss |
| 2026-08-18 23:45 UTC | 2026-08-18 23:49 UTC | 1918.65 | 1919.5 | 359 | 2002 | -0.85 | $-2.77 | stop_loss |
| 2026-08-19 11:16 UTC | 2026-08-19 12:34 UTC | 1923.55 | 1925.5 | 768 | 44462 | -1.95 | $-3.87 | stop_loss |
| 2026-08-19 13:37 UTC | 2026-08-19 14:50 UTC | 1930.5 | 1942.85 | 38985 | 178778 | -12.35 | $-14.29 | stop_loss |
| 2026-08-20 16:45 UTC | 2026-08-21 01:18 UTC | 2345.8 | 2359.35 | 51559 | 266954 | -13.55 | $-15.90 | stop_loss |
| 2026-08-21 01:54 UTC | 2026-08-21 06:05 UTC | 2366.55 | 2377.65 | 5693 | 36611 | -11.1 | $-13.47 | stop_loss |
| 2026-08-23 05:19 UTC | 2026-08-23 13:18 UTC | 2373.85 | 2445.07 | 195673 | 21496 | 71.22 | $+68.81 | stop_at_3pct |
| 2026-08-23 16:00 UTC | 2026-08-24 02:02 UTC | 2438.75 | 2425.2 | 36946 | 16962 | -13.55 | $-15.98 | stop_loss |
| 2026-08-24 11:46 UTC | 2026-08-24 12:51 UTC | 2498.85 | 2508.65 | 45963 | 242924 | -9.8 | $-12.30 | stop_loss |
| 2026-08-27 08:36 UTC | 2026-08-27 09:25 UTC | 2529.3 | 2544.1 | 53002 | 91468 | -14.8 | $-17.34 | stop_loss |
| 2026-08-27 09:42 UTC | 2026-08-28 14:32 UTC | 2544.2 | 2493.32 | 23473 | 103729 | 50.88 | $+48.37 | stop_at_2pct |
| 2026-08-28 17:32 UTC | 2026-08-28 18:22 UTC | 2441.8 | 2429.0 | 18463 | 912 | -12.8 | $-15.24 | stop_loss |
| 2026-08-28 18:51 UTC | 2026-08-30 20:40 UTC | 2418.9 | 2491.47 | 102914 | 3603 | 72.57 | $+70.11 | stop_at_3pct |
| 2026-08-30 20:54 UTC | 2026-08-31 00:15 UTC | 2496.1 | 2421.22 | 6359 | 26969 | 74.88 | $+72.42 | stop_at_3pct |
| 2026-09-01 18:50 UTC | 2026-09-02 00:00 UTC | 2397.5 | 2419.4 | 218051 | 9236 | 21.9 | $+19.49 | open_at_end |

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
If the rejection candle is red, it is the first red candle; enter short only when the next red candle breaks the first red candle low AND closes below the rally-green low (the green that made the swing high).
LONG setup: price must first reach the lower liquidity line (previous day low zone).
LONG entry: after the previous day low is broken/swept, wait for a bullish 1m rejection candle; its close may remain below the liquidity line.
If the rejection candle is green, it is the first green candle; ente...

---
_For research only. Past performance does not guarantee future results._