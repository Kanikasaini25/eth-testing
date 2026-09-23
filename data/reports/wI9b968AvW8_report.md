# Strategy Backtest Report

## Video
- URL: https://www.youtube.com/watch?v=wI9b968AvW8

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
| LQDTY Liquidity Strategy | 179 | 22.35% | 12.32% | 12.44% | 1.4% | Mixed |

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
| 2026-04-27 01:08 UTC | 2026-04-27 15:21 UTC | 2392.0 | 2272.4 | 9427 | 59814 | 119.6 | $+117.27 | take_profit_5pct |
| 2026-04-27 16:20 UTC | 2026-04-27 17:24 UTC | 2277.55 | 2284.75 | 694 | 21239 | -7.2 | $-9.48 | stop_loss |
| 2026-04-27 17:26 UTC | 2026-04-28 06:43 UTC | 2286.75 | 2272.3 | 110430 | 21413 | -14.45 | $-16.73 | stop_loss |
| 2026-04-28 14:53 UTC | 2026-04-29 12:22 UTC | 2266.65 | 2311.98 | 47926 | 5445 | 45.33 | $+43.04 | stop_at_2pct |
| 2026-04-29 13:04 UTC | 2026-04-29 20:44 UTC | 2315.0 | 2245.55 | 1083 | 60674 | 69.45 | $+67.17 | stop_at_3pct |
| 2026-04-29 20:48 UTC | 2026-04-29 21:23 UTC | 2245.0 | 2247.95 | 3473 | 22878 | -2.95 | $-5.20 | stop_loss |
| 2026-04-29 21:45 UTC | 2026-04-30 02:38 UTC | 2250.6 | 2237.3 | 6071 | 1010 | -13.3 | $-15.54 | stop_loss |
| 2026-05-01 03:29 UTC | 2026-05-01 12:17 UTC | 2284.25 | 2293.0 | 5090 | 51733 | -8.75 | $-11.04 | stop_loss |
| 2026-05-01 12:42 UTC | 2026-05-01 13:05 UTC | 2303.3 | 2309.2 | 26761 | 62300 | -5.9 | $-8.21 | stop_loss |
| 2026-05-02 21:54 UTC | 2026-05-03 19:34 UTC | 2324.5 | 2336.75 | 0 | 24145 | -12.25 | $-14.58 | stop_loss |
| 2026-05-03 22:23 UTC | 2026-05-04 01:56 UTC | 2340.35 | 2351.4 | 7612 | 36118 | -11.05 | $-13.40 | stop_loss |
| 2026-05-04 02:24 UTC | 2026-05-04 02:36 UTC | 2364.25 | 2371.65 | 4278 | 61055 | -7.4 | $-9.77 | stop_loss |
| 2026-05-06 09:46 UTC | 2026-05-06 11:17 UTC | 2410.65 | 2417.3 | 12314 | 146670 | -6.65 | $-9.06 | stop_loss |
| 2026-05-06 11:24 UTC | 2026-05-06 14:45 UTC | 2418.1 | 2369.74 | 14114 | 92296 | 48.36 | $+45.97 | stop_at_2pct |
| 2026-05-06 14:51 UTC | 2026-05-08 11:20 UTC | 2363.9 | 2292.98 | 9305 | 61326 | 70.92 | $+68.59 | stop_at_3pct |
| 2026-05-08 13:34 UTC | 2026-05-08 13:39 UTC | 2275.3 | 2271.5 | 46403 | 5359 | -3.8 | $-6.07 | stop_loss |
| 2026-05-08 13:48 UTC | 2026-05-10 20:44 UTC | 2272.0 | 2340.16 | 35930 | 8890 | 68.16 | $+65.85 | stop_at_3pct |
| 2026-05-10 23:17 UTC | 2026-05-11 15:26 UTC | 2376.4 | 2328.87 | 5694 | 14987 | 47.53 | $+45.18 | stop_at_2pct |
| 2026-05-12 07:12 UTC | 2026-05-12 07:46 UTC | 2302.25 | 2295.0 | 68375 | 1425 | -7.25 | $-9.55 | stop_loss |
| 2026-05-12 08:19 UTC | 2026-05-12 11:08 UTC | 2285.0 | 2278.55 | 28439 | 1297 | -6.45 | $-8.73 | stop_loss |
| 2026-05-13 15:43 UTC | 2026-05-13 15:45 UTC | 2252.7 | 2250.5 | 31527 | 4564 | -2.2 | $-4.45 | stop_loss |
| 2026-05-13 16:00 UTC | 2026-05-14 23:46 UTC | 2239.25 | 2284.03 | 137120 | 35465 | 44.78 | $+42.52 | stop_at_2pct |
| 2026-05-15 05:39 UTC | 2026-05-15 13:31 UTC | 2240.0 | 2236.25 | 141931 | 6498 | -3.75 | $-5.99 | stop_loss |
| 2026-05-15 14:12 UTC | 2026-05-16 07:12 UTC | 2217.55 | 2203.75 | 95179 | 5166 | -13.8 | $-16.01 | stop_loss |
| 2026-05-16 07:17 UTC | 2026-05-16 09:17 UTC | 2191.8 | 2180.3 | 116766 | 31100 | -11.5 | $-13.69 | stop_loss |
| 2026-05-18 18:35 UTC | 2026-05-18 19:00 UTC | 2090.35 | 2078.55 | 43057 | 7338 | -11.8 | $-13.88 | stop_loss |
| 2026-05-20 17:37 UTC | 2026-05-21 01:15 UTC | 2143.3 | 2148.0 | 1638 | 71737 | -4.7 | $-6.85 | stop_loss |
| 2026-05-21 01:19 UTC | 2026-05-23 07:46 UTC | 2144.65 | 2037.42 | 21516 | 68633 | 107.23 | $+105.14 | take_profit_5pct |
| 2026-05-23 08:54 UTC | 2026-05-23 20:50 UTC | 2028.4 | 2129.82 | 7862 | 2843 | 101.42 | $+99.34 | take_profit_5pct |
| 2026-05-23 20:53 UTC | 2026-05-23 21:03 UTC | 2133.15 | 2126.65 | 25733 | 10170 | -6.5 | $-8.63 | stop_loss |
| 2026-05-25 15:14 UTC | 2026-05-25 16:50 UTC | 2131.75 | 2137.7 | 1490 | 92575 | -5.95 | $-8.08 | stop_loss |
| 2026-05-25 17:10 UTC | 2026-05-27 08:26 UTC | 2135.3 | 2092.59 | 12301 | 43957 | 42.71 | $+40.59 | stop_at_2pct |
| 2026-05-27 18:22 UTC | 2026-05-27 21:40 UTC | 2048.45 | 2042.1 | 43375 | 4605 | -6.35 | $-8.40 | stop_loss |
| 2026-05-27 22:21 UTC | 2026-05-28 01:28 UTC | 2025.5 | 2014.75 | 6218 | 3300 | -10.75 | $-12.77 | stop_loss |
| 2026-05-28 01:43 UTC | 2026-05-28 03:11 UTC | 2018.1 | 2011.0 | 46116 | 1737 | -7.1 | $-9.11 | stop_loss |
| 2026-05-29 15:42 UTC | 2026-06-01 15:36 UTC | 2038.2 | 1977.05 | 1532 | 212824 | 61.15 | $+59.14 | stop_at_3pct |
| 2026-06-01 16:00 UTC | 2026-06-01 16:12 UTC | 1968.05 | 1959.0 | 64203 | 17465 | -9.05 | $-11.01 | stop_loss |
| 2026-06-01 16:14 UTC | 2026-06-02 14:21 UTC | 1962.8 | 1957.75 | 163128 | 13974 | -5.05 | $-7.01 | stop_loss |
| 2026-06-02 14:33 UTC | 2026-06-02 14:41 UTC | 1942.15 | 1933.5 | 127499 | 20922 | -8.65 | $-10.59 | stop_loss |
| 2026-06-03 03:52 UTC | 2026-06-03 13:45 UTC | 1825.55 | 1862.06 | 143612 | 18946 | 36.51 | $+34.67 | stop_at_2pct |
| 2026-06-03 13:49 UTC | 2026-06-03 14:18 UTC | 1863.7 | 1860.5 | 95750 | 44931 | -3.2 | $-5.06 | stop_loss |
| 2026-06-03 15:49 UTC | 2026-06-03 15:54 UTC | 1840.6 | 1836.6 | 51532 | 16930 | -4.0 | $-5.84 | stop_loss |
| 2026-06-04 08:23 UTC | 2026-06-04 09:06 UTC | 1767.6 | 1762.6 | 44543 | 12635 | -5.0 | $-6.77 | stop_loss |
| 2026-06-04 09:32 UTC | 2026-06-04 10:47 UTC | 1748.65 | 1743.35 | 117898 | 11575 | -5.3 | $-7.05 | stop_loss |
| 2026-06-05 06:05 UTC | 2026-06-05 06:16 UTC | 1677.3 | 1665.5 | 167146 | 50062 | -11.8 | $-13.47 | stop_loss |
| 2026-06-05 07:26 UTC | 2026-06-05 13:51 UTC | 1651.2 | 1636.25 | 73638 | 27272 | -14.95 | $-16.59 | stop_loss |
| 2026-06-06 04:51 UTC | 2026-06-06 05:02 UTC | 1519.3 | 1508.5 | 85302 | 13064 | -10.8 | $-12.31 | stop_loss |
| 2026-06-06 05:09 UTC | 2026-06-06 05:28 UTC | 1517.9 | 1548.26 | 112698 | 20372 | 30.36 | $+28.82 | stop_at_2pct |
| 2026-06-06 06:53 UTC | 2026-06-06 06:57 UTC | 1560.45 | 1556.0 | 90191 | 38806 | -4.45 | $-6.01 | stop_loss |
| 2026-06-07 05:32 UTC | 2026-06-07 06:24 UTC | 1601.0 | 1608.35 | 6163 | 122980 | -7.35 | $-8.95 | stop_loss |
| 2026-06-07 06:38 UTC | 2026-06-07 08:45 UTC | 1615.5 | 1622.95 | 29230 | 190397 | -7.45 | $-9.07 | stop_loss |
| 2026-06-09 14:32 UTC | 2026-06-09 14:47 UTC | 1642.9 | 1634.0 | 166804 | 37041 | -8.9 | $-10.54 | stop_loss |
| 2026-06-09 14:51 UTC | 2026-06-09 16:03 UTC | 1637.65 | 1632.8 | 139221 | 9060 | -4.85 | $-6.49 | stop_loss |
| 2026-06-10 09:25 UTC | 2026-06-10 14:15 UTC | 1612.0 | 1644.24 | 122104 | 1075 | 32.24 | $+30.61 | stop_at_2pct |
| 2026-06-10 14:22 UTC | 2026-06-10 16:48 UTC | 1643.7 | 1633.4 | 115483 | 28149 | -10.3 | $-11.94 | stop_loss |
| 2026-06-10 21:56 UTC | 2026-06-10 21:57 UTC | 1611.25 | 1607.0 | 16687 | 2065 | -4.25 | $-5.86 | stop_loss |
| 2026-06-11 18:51 UTC | 2026-06-11 19:33 UTC | 1684.05 | 1691.0 | 2438 | 31522 | -6.95 | $-8.64 | stop_loss |
| 2026-06-11 19:39 UTC | 2026-06-13 21:42 UTC | 1684.25 | 1691.15 | 339 | 27719 | -6.9 | $-8.59 | stop_loss |
| 2026-06-14 14:59 UTC | 2026-06-15 10:54 UTC | 1657.9 | 1740.8 | 15290 | 4149 | 82.89 | $+81.20 | take_profit_5pct |
| 2026-06-15 12:34 UTC | 2026-06-15 12:36 UTC | 1763.8 | 1765.85 | 5700 | 31732 | -2.05 | $-3.81 | stop_loss |
| 2026-06-15 12:47 UTC | 2026-06-15 12:48 UTC | 1772.55 | 1774.9 | 11158 | 63456 | -2.35 | $-4.12 | stop_loss |
| 2026-06-17 12:31 UTC | 2026-06-17 14:47 UTC | 1747.8 | 1742.1 | 113179 | 29099 | -5.7 | $-7.44 | stop_loss |
| 2026-06-17 15:14 UTC | 2026-06-17 18:05 UTC | 1757.0 | 1750.35 | 61605 | 2466 | -6.65 | $-8.40 | stop_loss |
| 2026-06-18 05:09 UTC | 2026-06-18 15:29 UTC | 1724.35 | 1721.3 | 79812 | 2445 | -3.05 | $-4.77 | stop_loss |
| 2026-06-18 16:01 UTC | 2026-06-18 17:23 UTC | 1686.85 | 1678.5 | 203368 | 31747 | -8.35 | $-10.03 | stop_loss |
| 2026-06-20 05:22 UTC | 2026-06-20 14:46 UTC | 1723.4 | 1732.8 | 18044 | 56067 | -9.4 | $-11.13 | stop_loss |
| 2026-06-20 15:42 UTC | 2026-06-22 01:26 UTC | 1738.5 | 1749.2 | 894 | 19182 | -10.7 | $-12.44 | stop_loss |
| 2026-06-22 02:06 UTC | 2026-06-22 11:06 UTC | 1740.15 | 1754.0 | 7255 | 18074 | -13.85 | $-15.60 | stop_loss |
| 2026-06-23 06:29 UTC | 2026-06-23 08:00 UTC | 1686.5 | 1680.05 | 52841 | 21236 | -6.45 | $-8.13 | stop_loss |
| 2026-06-23 09:00 UTC | 2026-06-24 13:48 UTC | 1650.3 | 1640.95 | 40163 | 2108 | -9.35 | $-11.00 | stop_loss |
| 2026-06-24 15:51 UTC | 2026-06-24 15:56 UTC | 1622.05 | 1616.25 | 88643 | 25794 | -5.8 | $-7.42 | stop_loss |
| 2026-06-25 15:18 UTC | 2026-06-26 02:12 UTC | 1553.0 | 1543.55 | 228036 | 45681 | -9.45 | $-11.00 | stop_loss |
| 2026-06-26 02:25 UTC | 2026-06-26 03:01 UTC | 1527.85 | 1518.25 | 65258 | 33909 | -9.6 | $-11.12 | stop_loss |
| 2026-06-27 14:50 UTC | 2026-06-27 15:07 UTC | 1595.0 | 1598.25 | 6328 | 39280 | -3.25 | $-4.85 | stop_loss |
| 2026-06-27 15:16 UTC | 2026-06-27 15:38 UTC | 1605.15 | 1608.05 | 19787 | 89193 | -2.9 | $-4.51 | stop_loss |
| 2026-06-28 19:54 UTC | 2026-06-28 22:52 UTC | 1564.15 | 1556.65 | 64416 | 9603 | -7.5 | $-9.06 | stop_loss |
| 2026-06-28 23:00 UTC | 2026-06-29 17:46 UTC | 1557.5 | 1635.38 | 19544 | 703 | 77.88 | $+76.28 | take_profit_5pct |
| 2026-06-29 17:54 UTC | 2026-06-30 18:19 UTC | 1630.3 | 1581.39 | 19946 | 35046 | 48.91 | $+47.30 | stop_at_3pct |
| 2026-07-01 15:08 UTC | 2026-07-01 15:23 UTC | 1611.9 | 1615.85 | 45788 | 188231 | -3.95 | $-5.56 | stop_loss |
| 2026-07-01 16:29 UTC | 2026-07-01 21:33 UTC | 1623.35 | 1628.25 | 8158 | 156587 | -4.9 | $-6.53 | stop_loss |
| 2026-07-02 10:44 UTC | 2026-07-02 11:10 UTC | 1645.55 | 1648.45 | 4279 | 55886 | -2.9 | $-4.55 | stop_loss |
| 2026-07-02 11:17 UTC | 2026-07-02 12:14 UTC | 1648.9 | 1654.15 | 7883 | 46435 | -5.25 | $-6.90 | stop_loss |
| 2026-07-03 10:07 UTC | 2026-07-03 10:12 UTC | 1729.7 | 1731.85 | 4010 | 24188 | -2.15 | $-3.88 | stop_loss |
| 2026-07-03 11:11 UTC | 2026-07-03 13:41 UTC | 1741.3 | 1748.4 | 8537 | 69562 | -7.1 | $-8.84 | stop_loss |
| 2026-07-04 16:13 UTC | 2026-07-04 17:50 UTC | 1784.55 | 1796.75 | 25599 | 73818 | -12.2 | $-13.99 | stop_loss |
| 2026-07-04 17:58 UTC | 2026-07-05 22:30 UTC | 1799.9 | 1807.0 | 7956 | 85789 | -7.1 | $-8.90 | stop_loss |
| 2026-07-06 12:12 UTC | 2026-07-06 13:02 UTC | 1745.95 | 1734.35 | 173431 | 20162 | -11.6 | $-13.34 | stop_loss |
| 2026-07-06 13:06 UTC | 2026-07-06 13:16 UTC | 1734.55 | 1732.5 | 99788 | 22602 | -2.05 | $-3.78 | stop_loss |
| 2026-07-08 01:43 UTC | 2026-07-08 02:01 UTC | 1755.95 | 1749.2 | 42270 | 3635 | -6.75 | $-8.50 | stop_loss |
| 2026-07-08 02:18 UTC | 2026-07-08 02:32 UTC | 1751.8 | 1748.2 | 52257 | 4671 | -3.6 | $-5.35 | stop_loss |
| 2026-07-10 01:55 UTC | 2026-07-10 03:49 UTC | 1770.2 | 1776.9 | 10439 | 66904 | -6.7 | $-8.47 | stop_loss |
| 2026-07-10 03:54 UTC | 2026-07-10 04:17 UTC | 1775.1 | 1779.1 | 4178 | 26719 | -4.0 | $-5.78 | stop_loss |
| 2026-07-11 15:31 UTC | 2026-07-11 17:40 UTC | 1822.0 | 1827.2 | 13716 | 25849 | -5.2 | $-7.02 | stop_loss |
| 2026-07-11 17:57 UTC | 2026-07-11 18:21 UTC | 1824.2 | 1827.95 | 3664 | 11928 | -3.75 | $-5.58 | stop_loss |
| 2026-07-12 00:11 UTC | 2026-07-12 00:31 UTC | 1785.25 | 1782.2 | 24084 | 2314 | -3.05 | $-4.83 | stop_loss |
| 2026-07-12 00:33 UTC | 2026-07-13 00:38 UTC | 1784.3 | 1819.99 | 41148 | 6961 | 35.69 | $+33.88 | stop_at_2pct |
| 2026-07-13 01:00 UTC | 2026-07-13 19:34 UTC | 1825.6 | 1770.83 | 9288 | 20957 | 54.77 | $+52.97 | stop_at_3pct |
| 2026-07-13 19:46 UTC | 2026-07-13 19:50 UTC | 1770.4 | 1771.3 | 858 | 15104 | -0.9 | $-2.67 | stop_loss |
| 2026-07-13 19:56 UTC | 2026-07-13 20:51 UTC | 1772.7 | 1762.75 | 66911 | 3716 | -9.95 | $-11.72 | stop_loss |
| 2026-07-14 13:35 UTC | 2026-07-14 14:59 UTC | 1871.5 | 1881.95 | 29263 | 93300 | -10.45 | $-12.33 | stop_loss |
| 2026-07-14 15:06 UTC | 2026-07-14 15:30 UTC | 1875.3 | 1884.0 | 9864 | 55984 | -8.7 | $-10.58 | stop_loss |
| 2026-07-15 13:05 UTC | 2026-07-15 13:21 UTC | 1936.35 | 1944.15 | 34981 | 264786 | -7.8 | $-9.74 | stop_loss |
| 2026-07-15 13:25 UTC | 2026-07-17 05:25 UTC | 1938.5 | 1841.57 | 86985 | 146151 | 96.93 | $+95.03 | take_profit_5pct |
| 2026-07-17 05:48 UTC | 2026-07-17 05:51 UTC | 1827.7 | 1824.0 | 98860 | 17352 | -3.7 | $-5.53 | stop_loss |
| 2026-07-17 05:54 UTC | 2026-07-17 05:58 UTC | 1824.7 | 1821.65 | 66726 | 4704 | -3.05 | $-4.87 | stop_loss |
| 2026-07-19 02:17 UTC | 2026-07-19 02:33 UTC | 1868.85 | 1872.25 | 1941 | 49201 | -3.4 | $-5.27 | stop_loss |
| 2026-07-19 02:47 UTC | 2026-07-19 10:48 UTC | 1871.65 | 1877.0 | 7044 | 29053 | -5.35 | $-7.22 | stop_loss |
| 2026-07-20 00:21 UTC | 2026-07-20 11:36 UTC | 1881.3 | 1891.25 | 1616 | 63952 | -9.95 | $-11.84 | stop_loss |
| 2026-07-20 11:45 UTC | 2026-07-20 11:58 UTC | 1886.6 | 1894.5 | 18071 | 59627 | -7.9 | $-9.79 | stop_loss |
| 2026-07-21 03:17 UTC | 2026-07-21 04:01 UTC | 1922.4 | 1927.9 | 8976 | 34161 | -5.5 | $-7.43 | stop_loss |
| 2026-07-21 04:09 UTC | 2026-07-21 05:48 UTC | 1928.15 | 1930.5 | 1949 | 31024 | -2.35 | $-4.28 | stop_loss |
| 2026-07-22 16:41 UTC | 2026-07-24 07:02 UTC | 1950.45 | 1891.94 | 19157 | 78835 | 58.51 | $+56.59 | stop_at_3pct |
| 2026-07-24 13:57 UTC | 2026-07-24 14:46 UTC | 1851.35 | 1847.05 | 134841 | 22763 | -4.3 | $-6.15 | stop_loss |
| 2026-07-24 14:50 UTC | 2026-07-26 22:35 UTC | 1853.25 | 1945.91 | 120057 | 16503 | 92.66 | $+90.76 | take_profit_5pct |
| 2026-07-26 22:46 UTC | 2026-07-26 22:48 UTC | 1944.7 | 1947.25 | 13542 | 37787 | -2.55 | $-4.50 | stop_loss |
| 2026-07-26 23:18 UTC | 2026-07-27 05:58 UTC | 1957.6 | 1966.6 | 4299 | 22761 | -9.0 | $-10.96 | stop_loss |
| 2026-07-27 06:18 UTC | 2026-07-28 01:06 UTC | 1968.05 | 1869.65 | 14231 | 22640 | 98.4 | $+96.48 | take_profit_5pct |
| 2026-07-28 01:27 UTC | 2026-07-28 13:39 UTC | 1875.55 | 1865.15 | 18893 | 7585 | -10.4 | $-12.27 | stop_loss |
| 2026-07-28 13:56 UTC | 2026-07-28 17:16 UTC | 1871.0 | 1908.42 | 107274 | 10058 | 37.42 | $+35.53 | stop_at_2pct |
| 2026-07-28 18:00 UTC | 2026-07-29 03:51 UTC | 1901.65 | 1892.0 | 122037 | 30723 | -9.65 | $-11.55 | stop_loss |
| 2026-07-31 07:31 UTC | 2026-07-31 09:22 UTC | 1886.85 | 1883.4 | 91009 | 15223 | -3.45 | $-5.34 | stop_loss |
| 2026-07-31 10:13 UTC | 2026-07-31 12:10 UTC | 1882.65 | 1876.55 | 39781 | 7979 | -6.1 | $-7.98 | stop_loss |
| 2026-08-01 18:56 UTC | 2026-08-03 01:28 UTC | 1831.1 | 1867.72 | 106749 | 16153 | 36.62 | $+34.77 | stop_at_2pct |
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
| 2026-09-01 18:50 UTC | 2026-09-02 01:50 UTC | 2397.5 | 2387.85 | 218051 | 9236 | -9.65 | $-12.04 | stop_loss |
| 2026-09-02 09:47 UTC | 2026-09-02 10:31 UTC | 2369.65 | 2365.35 | 136762 | 23993 | -4.3 | $-6.67 | stop_loss |
| 2026-09-03 13:46 UTC | 2026-09-03 14:11 UTC | 2430.05 | 2435.5 | 23624 | 153161 | -5.45 | $-7.88 | stop_loss |
| 2026-09-03 14:19 UTC | 2026-09-03 14:23 UTC | 2437.4 | 2443.9 | 14149 | 97725 | -6.5 | $-8.94 | stop_loss |
| 2026-09-04 09:20 UTC | 2026-09-04 12:35 UTC | 2537.5 | 2461.38 | 14434 | 166000 | 76.12 | $+73.63 | stop_at_3pct |
| 2026-09-04 13:33 UTC | 2026-09-04 13:47 UTC | 2447.9 | 2462.65 | 10160 | 40889 | -14.75 | $-17.21 | stop_loss |
| 2026-09-06 01:18 UTC | 2026-09-06 01:36 UTC | 2494.8 | 2498.7 | 2748 | 21137 | -3.9 | $-6.40 | stop_loss |
| 2026-09-06 02:02 UTC | 2026-09-06 03:40 UTC | 2504.9 | 2510.1 | 18938 | 36293 | -5.2 | $-7.71 | stop_loss |
| 2026-09-07 02:45 UTC | 2026-09-08 14:12 UTC | 2525.5 | 2474.99 | 10522 | 24982 | 50.51 | $+48.01 | stop_at_2pct |
| 2026-09-09 07:14 UTC | 2026-09-09 08:09 UTC | 2510.0 | 2516.45 | 4920 | 45384 | -6.45 | $-8.96 | stop_loss |
| 2026-09-09 08:43 UTC | 2026-09-09 23:49 UTC | 2517.4 | 2467.05 | 937 | 15636 | 50.35 | $+47.86 | stop_at_2pct |
| 2026-09-09 23:55 UTC | 2026-09-10 00:00 UTC | 2466.7 | 2467.95 | 3770 | 10443 | -1.25 | $-3.72 | stop_loss |
| 2026-09-10 13:27 UTC | 2026-09-11 13:37 UTC | 2417.3 | 2489.82 | 26174 | 6573 | 72.52 | $+70.07 | stop_at_3pct |
| 2026-09-11 15:25 UTC | 2026-09-12 08:45 UTC | 2611.5 | 2533.15 | 8427 | 34040 | 78.35 | $+75.77 | stop_at_3pct |
| 2026-09-13 09:35 UTC | 2026-09-13 10:57 UTC | 2475.2 | 2469.35 | 137250 | 32403 | -5.85 | $-8.32 | stop_loss |
| 2026-09-13 11:04 UTC | 2026-09-13 13:24 UTC | 2474.7 | 2466.75 | 61988 | 7374 | -7.95 | $-10.42 | stop_loss |
| 2026-09-14 16:26 UTC | 2026-09-14 16:48 UTC | 2522.0 | 2530.45 | 10539 | 117574 | -8.45 | $-10.98 | stop_loss |
| 2026-09-14 16:58 UTC | 2026-09-14 18:22 UTC | 2528.65 | 2537.0 | 12514 | 76925 | -8.35 | $-10.88 | stop_loss |
| 2026-09-15 13:44 UTC | 2026-09-15 14:35 UTC | 2446.25 | 2431.3 | 120804 | 33867 | -14.95 | $-17.39 | stop_loss |
| 2026-09-15 14:58 UTC | 2026-09-15 15:01 UTC | 2404.95 | 2396.75 | 196808 | 3642 | -8.2 | $-10.60 | stop_loss |
| 2026-09-17 01:38 UTC | 2026-09-17 05:01 UTC | 2437.35 | 2444.15 | 2250 | 28221 | -6.8 | $-9.24 | stop_loss |
| 2026-09-17 05:03 UTC | 2026-09-17 06:47 UTC | 2441.7 | 2445.75 | 9289 | 47996 | -4.05 | $-6.49 | stop_loss |
| 2026-09-18 03:19 UTC | 2026-09-18 05:08 UTC | 2478.25 | 2484.85 | 26578 | 88827 | -6.6 | $-9.08 | stop_loss |
| 2026-09-18 05:21 UTC | 2026-09-18 07:03 UTC | 2484.95 | 2492.6 | 2811 | 55283 | -7.65 | $-10.14 | stop_loss |
| 2026-09-19 08:48 UTC | 2026-09-19 09:08 UTC | 2647.35 | 2657.4 | 0 | 28703 | -10.05 | $-12.70 | stop_loss |
| 2026-09-19 09:29 UTC | 2026-09-19 17:18 UTC | 2648.95 | 2659.5 | 13719 | 60905 | -10.55 | $-13.20 | stop_loss |
| 2026-09-20 03:11 UTC | 2026-09-20 11:03 UTC | 2581.85 | 2567.3 | 34249 | 5928 | -14.55 | $-17.12 | stop_loss |
| 2026-09-20 11:20 UTC | 2026-09-20 17:27 UTC | 2571.05 | 2622.47 | 20403 | 796 | 51.42 | $+48.82 | stop_at_2pct |
| 2026-09-20 17:38 UTC | 2026-09-20 21:03 UTC | 2631.25 | 2617.15 | 57504 | 17408 | -14.1 | $-16.72 | stop_loss |
| 2026-09-21 00:42 UTC | 2026-09-21 00:46 UTC | 2685.8 | 2696.6 | 5581 | 21798 | -10.8 | $-13.49 | stop_loss |
| 2026-09-21 00:49 UTC | 2026-09-21 08:38 UTC | 2695.25 | 2706.95 | 18788 | 151241 | -11.7 | $-14.40 | stop_loss |
| 2026-09-23 03:49 UTC | 2026-09-23 04:23 UTC | 2775.85 | 2782.85 | 9530 | 20191 | -7.0 | $-9.78 | stop_loss |
| 2026-09-23 04:29 UTC | 2026-09-23 16:01 UTC | 2783.0 | 2643.85 | 473 | 72597 | 139.15 | $+136.44 | take_profit_5pct |
| 2026-09-23 16:28 UTC | 2026-09-23 18:13 UTC | 2660.25 | 2663.0 | 4848 | 16996 | -2.75 | $-5.41 | open_at_end |

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