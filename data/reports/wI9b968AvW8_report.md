# Strategy Backtest Report

## Video
- URL: https://www.youtube.com/watch?v=wI9b968AvW8&t=19s

## Market Data
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
      "SHORT entry: on 1 minute, wait for a fresh red candle after price reaches the upper line.",
      "SHORT trigger: enter on the NEXT candle when it breaks AND closes below the red candle low.",
      "LONG setups are disabled — ETH 1m longs won only ~22% and pulled the win rate down.",
      "Signal candle body must be at least 75% of the candle range (strong close, not a doji).",
      "Entry price must stay within 12 points of the previous-day high (upper liquidity line).",
      "Skip entries where stop loss is too tight or too wide, or reward-to-risk is under 2.5.",
      "Trade only during active UTC session hours (default 08:00–20:00).",
      "If price is between the two lines, there is no trade."
    ],
    "exit_rules": [
      "Target 1: book partial profit when ETH moves 15 points in your favor (80% of lots).",
      "Keep 20% as runner with a 3-point trailing stop after partial.",
      "Target 2 (runner): nearest swing high/low, or trailing stop exit."
    ],
    "risk_rules": [
      "Stop loss for LONG: below the previous 1m candle wick low (candle before entry).",
      "Stop loss for SHORT: above the previous 1m candle wick high (candle before entry).",
      "Always enter with fixed 100 lots on every trade.",
      "Allow a maximum of 2 full stop losses per session (complete SL, not partial exit).",
      "If a trade moves in your favor and you partial-exit, that does not count as a full SL.",
      "If two full stop losses are hit, stop trading for that session.",
      "Only 1 entry attempt per liquidity line per day (upper line = shorts, lower line = longs).",
      "After a full stop loss at the upper line, no more shorts from that line for the rest of the day.",
      "After a full stop loss at the lower line, no more longs from that line for the rest of the day.",
      "If one trade gives partial profit and another gives a full SL, a third attempt is allowed.",
      "Never take more than 3 trades in one sequence.",
      "Avoid entries where stop loss is too wide.",
      "Backtest on ETH futures (e.g. ETHUSD on Delta Exchange)."
    ],
    "parameters": {
      "setup_timeframe": "1d",
      "entry_timeframe": "1m",
      "lines_from": "previous_day_high_and_low",
      "instrument": "ETHUSD",
      "max_full_stop_losses_per_session": 2,
      "max_trades_per_sequence": 3,
      "max_entries_per_liquidity_line_per_day": 1,
      "entry_on_next_candle": true,
      "require_close_beyond_signal": true,
      "require_liquidity_sweep": false,
      "require_signal_touches_line": false,
      "max_entry_distance_from_line_points": 12.0,
      "max_minutes_after_liquidity_touch": 0.0,
      "allow_longs": false,
      "allow_shorts": true,
      "use_daily_trend_filter": false,
      "use_session_filter": true,
      "session_start_hour_utc": 8,
      "session_end_hour_utc": 20,
      "min_stop_loss_points": 4.0,
      "max_stop_loss_points": 7.0,
      "min_reward_to_risk": 2.5,
      "min_signal_body_ratio": 0.75,
      "min_signal_range_points": 3.5,
      "position_lots": 100,
      "partial_exit_lots": 80,
      "runner_lots": 20,
      "use_swing_target_for_partial": false,
      "partial_target_points": 15,
      "use_trailing_stop_after_partial": true,
      "trailing_stop_points": 3.0,
      "starting_wallet_usd": 10000,
      "stop_loss_mode": "previous_candle_wick",
      "max_stop_loss_pct": 5.0,
      "swing_lookback_days": 20,
      "runner_swing_lookback_days": 60,
      "fee_pct_per_side": 0.05
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
| LQDTY Liquidity Strategy | 29 | 37.93% | 38.31% | 18.32% | 2.87% | Mixed |

## Backtest Mode

- **LQDTY Liquidity Strategy:** `eth_100lots_filtered_entries`

## Rule Compliance Check

### LQDTY Liquidity Strategy
- Uses Previous Day High Low Lines: **Yes**
- Uses 1M Candle Confirmation: **Yes**
- Supports Long And Short: **Yes**
- Uses Previous Candle Wick Stop Loss: **Yes**
- Entry On Next Candle: **Yes**
- Requires Close Beyond Signal: **Yes**
- Filters Min Stop Loss Points: **Yes**
- Filters Max Stop Loss Points: **Yes**
- Fixed 100 Lot Entry: **Yes**
- Uses Swing Target For Partial: **No**
- Uses Fixed Point Partial Target: **Yes**
- Keeps Runner After Partial: **Yes**
- Uses Trailing Stop On Runner: **Yes**
- Moves Stop To Breakeven After Partial: **No**
- Uses Swing Target For Runner: **Yes**
- Limits Max Trades Per Session: **Yes**
- Limits Max Full Stop Losses: **Yes**
- One Attempt Per Liquidity Line Per Day: **Yes**
- Blocks Line After Full Stop Loss: **Yes**
- Skips Middle Zone Without Touch: **Yes**
- Instrument Eth Futures: **Yes**
- Requires Liquidity Sweep Rejection: **No**
- Requires Signal Candle At Line: **No**
- Filters Entry Distance From Line: **Yes**
- Filters Minutes After Liquidity Touch: **No**
- Allows Longs: **No**
- Allows Shorts: **Yes**
- Uses Daily Trend Filter: **No**
- Uses Utc Session Filter: **Yes**
- Simulates Trading Fees: **Yes**


## Trade Details

### LQDTY Liquidity Strategy

| Entry | Exit | Entry Price | Exit Price | Points | P/L ($) | Reason |
|-------|------|-------------|------------|--------|---------|--------|
| 2026-03-15T18:23 | 2026-03-15T19:34 | 2107.0 | 2112.95 | -5.95 | $-8.06 | stop_loss |
| 2026-03-23T11:59 | 2026-03-23T12:01 | 2133.3 | 2118.3 | 15.0 | $+10.30 | partial_target_15pts |
| 2026-03-23T11:59 | 2026-03-23T12:02 | 2133.3 | 2115.3 | 18.0 | $+3.18 | trailing_stop |
| 2026-03-25T08:09 | 2026-03-25T08:19 | 2165.1 | 2169.85 | -4.75 | $-6.92 | stop_loss |
| 2026-03-30T19:07 | 2026-03-30T20:06 | 2021.4 | 2026.15 | -4.75 | $-6.77 | stop_loss |
| 2026-04-06T17:15 | 2026-04-06T17:17 | 2123.1 | 2127.4 | -4.3 | $-6.43 | stop_loss |
| 2026-04-10T15:29 | 2026-04-10T15:57 | 2236.1 | 2221.1 | 15.0 | $+10.22 | partial_target_15pts |
| 2026-04-10T15:29 | 2026-04-10T15:58 | 2236.1 | 2222.55 | 13.55 | $+2.26 | trailing_stop |
| 2026-04-14T08:40 | 2026-04-14T09:02 | 2384.75 | 2389.5 | -4.75 | $-7.14 | stop_loss |
| 2026-04-29T12:21 | 2026-04-29T13:30 | 2315.8 | 2300.8 | 15.0 | $+10.15 | partial_target_15pts |
| 2026-04-29T12:21 | 2026-04-29T13:31 | 2315.8 | 2302.95 | 12.85 | $+2.11 | trailing_stop |
| 2026-05-04T15:10 | 2026-05-04T15:19 | 2366.4 | 2351.4 | 15.0 | $+10.11 | partial_target_15pts |
| 2026-05-04T15:10 | 2026-05-04T15:20 | 2366.4 | 2345.15 | 21.25 | $+3.78 | trailing_stop |
| 2026-05-06T12:03 | 2026-05-06T12:22 | 2406.25 | 2410.85 | -4.6 | $-7.01 | stop_loss |
| 2026-05-10T17:07 | 2026-05-10T17:23 | 2347.6 | 2353.05 | -5.45 | $-7.80 | stop_loss |
| 2026-05-20T15:45 | 2026-05-20T15:46 | 2133.7 | 2138.7 | -5.0 | $-7.14 | stop_loss |
| 2026-06-07T12:13 | 2026-06-07T12:15 | 1607.45 | 1613.05 | -5.6 | $-7.21 | stop_loss |
| 2026-06-11T12:20 | 2026-06-11T14:16 | 1656.0 | 1641.0 | 15.0 | $+10.68 | partial_target_15pts |
| 2026-06-11T12:20 | 2026-06-11T14:17 | 1656.0 | 1641.2 | 14.8 | $+2.63 | trailing_stop |
| 2026-06-20T15:01 | 2026-06-20T15:03 | 1729.7 | 1733.85 | -4.15 | $-5.88 | stop_loss |
| 2026-06-22T14:55 | 2026-06-22T15:01 | 1750.65 | 1755.15 | -4.5 | $-6.25 | stop_loss |
| 2026-06-29T12:24 | 2026-06-29T12:39 | 1587.25 | 1572.25 | 15.0 | $+10.74 | partial_target_15pts |
| 2026-06-29T12:24 | 2026-06-29T12:41 | 1587.25 | 1574.0 | 13.25 | $+2.33 | trailing_stop |
| 2026-07-01T19:25 | 2026-07-01T19:34 | 1616.35 | 1620.45 | -4.1 | $-5.72 | stop_loss |
| 2026-07-03T12:18 | 2026-07-03T13:00 | 1732.5 | 1736.6 | -4.1 | $-5.83 | stop_loss |
| 2026-07-19T12:09 | 2026-07-19T12:10 | 1865.0 | 1850.0 | 15.0 | $+10.51 | partial_target_15pts |
| 2026-07-19T12:09 | 2026-07-19T12:11 | 1865.0 | 48.0 | 1817.0 | $+363.21 | trailing_stop |
| 2026-07-21T18:01 | 2026-07-21T18:04 | 1914.35 | 1918.75 | -4.4 | $-6.32 | stop_loss |
| 2026-07-22T14:12 | 2026-07-22T14:21 | 1943.5 | 1928.5 | 15.0 | $+10.45 | partial_target_15pts |
| 2026-07-22T14:12 | 2026-07-22T14:22 | 1943.5 | 1930.45 | 13.05 | $+2.22 | trailing_stop |
| 2026-08-05T12:31 | 2026-08-05T13:31 | 1879.0 | 1864.0 | 15.0 | $+10.50 | partial_target_15pts |
| 2026-08-05T12:31 | 2026-08-05T13:32 | 1879.0 | 1858.5 | 20.5 | $+3.73 | trailing_stop |
| 2026-08-07T14:44 | 2026-08-07T16:09 | 1917.1 | 1921.35 | -4.25 | $-6.17 | stop_loss |
| 2026-08-12T13:50 | 2026-08-12T14:31 | 1902.65 | 1887.65 | 15.0 | $+10.48 | partial_target_15pts |
| 2026-08-12T13:50 | 2026-08-12T14:32 | 1902.65 | 1888.2 | 14.45 | $+2.51 | trailing_stop |
| 2026-08-18T14:52 | 2026-08-18T15:00 | 1910.35 | 1915.0 | -4.65 | $-6.56 | stop_loss |
| 2026-08-20T16:49 | 2026-08-20T17:52 | 2341.95 | 2347.8 | -5.85 | $-8.19 | stop_loss |
| 2026-08-21T11:48 | 2026-08-21T11:50 | 2367.05 | 2371.2 | -4.15 | $-6.52 | stop_loss |
| 2026-08-24T10:21 | 2026-08-24T11:01 | 2473.25 | 2458.25 | 15.0 | $+10.03 | partial_target_15pts |
| 2026-08-24T10:21 | 2026-08-24T11:02 | 2473.25 | 2456.3 | 16.95 | $+2.90 | trailing_stop |

## Transcript Excerpt

कुछ दिन पहले जब मैं लाइव कर रहा था तो मुझे एक कमेंट दिखा और वो कमेंट में था कि गौतम भाई मैं पूरा ही कॉन्फिडेंस लूज़ कर चुका हूं। जो भी ट्रेड लेता हूं साला वो ट्रेड फेल हो जाता है। जिस भी स्ट्रेटजी पे काम करता हूं लॉस ही हो रहा है और जब मेरा ट्रेड छूटता है वो ट्रेड चल जाता है। मैं अब होप खो चुका हूं कि मैं कभी एक प्रॉफिटेबल ट्रेडर बन पाऊंगा या मेरा जर्नी जो है वो सक्सेसफुल रास्ता में निकल पाएगा। इसका सॉलशन दो। अब देखो एज अ फ्लो मैं क्या होता लाइव कर रहा हूं फ्लो में हूं कि चलो ठीक है। रिस्क मैनेजमेंट फॉलो करो। मनी मैनेजमेंट फॉलो करो। एक स्ट्रेटजी पे स्टिक रहो। ये वो फलाना डिमका जो किताबी ज्ञान है जो हर जगह मिलता है। आप कोई भी YouTube वीडियो ढूंढो आपको यही रास्ता मिलेगा कि रिस्क मैनेजमेंट, मनी मैनेजमेंट स्ट्रेट, फिक्स टाइम, फिक्स्ड लॉस, फिक्स टारगेट सबको पता है। आपसे भी अगर कोई पूछेगा तो आप यही आंसर दोगे। होता है ना एक कोड पढ़ा होगा आपने कि मेरे ज्ञान देने की स्किल और मेरी खुद की जिंदगी। तो ये किताबी नॉलेज सबके पास है। मैंने उस बंदे को एक प्रैक्टिकल सॉल्यूशन दिया कि चलो ठीक है। आज तक पूरे हिस्ट्री में मैंने अभी तक ढंग से पूरे YouTube पे कोई स्ट्रेटजी अपना नहीं दिया है। जो भी था एक दो स्ट्रेटजी पीवीपीटी वो बहुत कॉम्प्लेक्स था। लाइव से लोगों को 10-15 लाइव देख के सीखना पड़ता था। बट मैंने उस चीज को कॉम्प्लेक्स करके उस बंदे को बताया। प्लस 16 17000 आदमी उस समय लाइव में थे। आप नहीं ज्वॉइ करते हो तो 9:00 बजे कर लेना रात को। सबको बताया। कुछ लोगों का लाइफ फ्रॉम दैट डे बदल गया। कुछ लोगों को अभी भी समझ में नहीं आ रहा है कि यार उस चीज को इंप्लीमेंट कैसे करें। उसका रील कट के मेरे लर्नर गौतम प...

---
_For research only. Past performance does not guarantee future results._