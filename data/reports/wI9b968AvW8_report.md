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
      "LONG setup: price must first reach the lower liquidity line (previous day low zone).",
      "LONG entry: on 1 minute, wait for a fresh green candle after price reaches the lower line.",
      "LONG trigger: enter on the NEXT candle when it breaks AND closes above the green candle high.",
      "Signal candle must have a strong body and meaningful range.",
      "Skip entries where stop loss is too tight or too wide.",
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
      "use_daily_trend_filter": false,
      "use_session_filter": true,
      "session_start_hour_utc": 8,
      "session_end_hour_utc": 20,
      "min_stop_loss_points": 4.0,
      "max_stop_loss_points": 7.0,
      "min_reward_to_risk": 1.5,
      "min_signal_body_ratio": 0.55,
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
| LQDTY Liquidity Strategy | 6 | 50.0% | 0.17% | 19.39% | 0.13% | Mixed |

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
- Uses Daily Trend Filter: **No**
- Uses Utc Session Filter: **Yes**
- Simulates Trading Fees: **Yes**


## Trade Details

### LQDTY Liquidity Strategy

| Entry | Exit | Entry Price | Exit Price | Points | P/L ($) | Reason |
|-------|------|-------------|------------|--------|---------|--------|
| 2026-08-07T14:44 | 2026-08-07T16:09 | 1917.1 | 1921.35 | -4.25 | $-6.17 | stop_loss |
| 2026-08-10T14:01 | 2026-08-10T14:09 | 1901.25 | 1896.1 | -5.15 | $-7.05 | stop_loss |
| 2026-08-11T19:54 | 2026-08-12T08:06 | 1880.15 | 1895.15 | 15.0 | $+10.49 | partial_target_15pts |
| 2026-08-11T19:54 | 2026-08-12T08:13 | 1880.15 | 1892.45 | 12.3 | $+2.08 | trailing_stop |
| 2026-08-12T13:50 | 2026-08-12T14:31 | 1902.65 | 1887.65 | 15.0 | $+10.48 | partial_target_15pts |
| 2026-08-12T13:50 | 2026-08-12T14:32 | 1902.65 | 1888.2 | 14.45 | $+2.51 | trailing_stop |
| 2026-08-13T16:47 | 2026-08-13T19:07 | 1873.15 | 1888.15 | 15.0 | $+10.50 | partial_target_15pts |
| 2026-08-13T16:47 | 2026-08-13T19:12 | 1873.15 | 1888.7 | 15.55 | $+2.73 | trailing_stop |
| 2026-08-18T14:32 | 2026-08-19T08:46 | 1915.65 | 1922.4 | -6.75 | $-8.67 | stop_loss |

## Transcript Excerpt

कुछ दिन पहले जब मैं लाइव कर रहा था तो मुझे एक कमेंट दिखा और वो कमेंट में था कि गौतम भाई मैं पूरा ही कॉन्फिडेंस लूज़ कर चुका हूं। जो भी ट्रेड लेता हूं साला वो ट्रेड फेल हो जाता है। जिस भी स्ट्रेटजी पे काम करता हूं लॉस ही हो रहा है और जब मेरा ट्रेड छूटता है वो ट्रेड चल जाता है। मैं अब होप खो चुका हूं कि मैं कभी एक प्रॉफिटेबल ट्रेडर बन पाऊंगा या मेरा जर्नी जो है वो सक्सेसफुल रास्ता में निकल पाएगा। इसका सॉलशन दो। अब देखो एज अ फ्लो मैं क्या होता लाइव कर रहा हूं फ्लो में हूं कि चलो ठीक है। रिस्क मैनेजमेंट फॉलो करो। मनी मैनेजमेंट फॉलो करो। एक स्ट्रेटजी पे स्टिक रहो। ये वो फलाना डिमका जो किताबी ज्ञान है जो हर जगह मिलता है। आप कोई भी YouTube वीडियो ढूंढो आपको यही रास्ता मिलेगा कि रिस्क मैनेजमेंट, मनी मैनेजमेंट स्ट्रेट, फिक्स टाइम, फिक्स्ड लॉस, फिक्स टारगेट सबको पता है। आपसे भी अगर कोई पूछेगा तो आप यही आंसर दोगे। होता है ना एक कोड पढ़ा होगा आपने कि मेरे ज्ञान देने की स्किल और मेरी खुद की जिंदगी। तो ये किताबी नॉलेज सबके पास है। मैंने उस बंदे को एक प्रैक्टिकल सॉल्यूशन दिया कि चलो ठीक है। आज तक पूरे हिस्ट्री में मैंने अभी तक ढंग से पूरे YouTube पे कोई स्ट्रेटजी अपना नहीं दिया है। जो भी था एक दो स्ट्रेटजी पीवीपीटी वो बहुत कॉम्प्लेक्स था। लाइव से लोगों को 10-15 लाइव देख के सीखना पड़ता था। बट मैंने उस चीज को कॉम्प्लेक्स करके उस बंदे को बताया। प्लस 16 17000 आदमी उस समय लाइव में थे। आप नहीं ज्वॉइ करते हो तो 9:00 बजे कर लेना रात को। सबको बताया। कुछ लोगों का लाइफ फ्रॉम दैट डे बदल गया। कुछ लोगों को अभी भी समझ में नहीं आ रहा है कि यार उस चीज को इंप्लीमेंट कैसे करें। उसका रील कट के मेरे लर्नर गौतम प...

---
_For research only. Past performance does not guarantee future results._