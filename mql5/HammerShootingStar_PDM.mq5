//+------------------------------------------------------------------+
//|                                      HammerShootingStar_PDM.mq5  |
//| Local laptop EA for PDMBulls MT5 (Linux/Windows) — no Delta,     |
//| no Python MetaTrader5 package required.                           |
//| Attach to XAUUSD (or your symbol) M1 chart.                       |
//+------------------------------------------------------------------+
#property copyright "eth-testing"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

input group "=== Account / Size ==="
input double   InpLots              = 0.10;     // Lot size
input ulong    InpMagic             = 260903;   // Magic number
input int      InpSlippage          = 40;       // Max slippage (points)

input group "=== Pattern timeframe ==="
input ENUM_TIMEFRAMES InpPatternTF  = PERIOD_M15; // Pattern candle TF
input int      InpTrendLookback     = 6;        // Trend lookback bars
input double   InpMinShadowRatio    = 2.0;      // Wick / body min ratio
input double   InpMinPatternPoints  = 1.5;      // Min candle range (price)

input group "=== Confirmation / Risk ==="
input double   InpSlBuffer          = 0.50;     // Extra SL buffer
input double   InpTargetPoints      = 40.0;     // T1 distance
input double   InpMinConfirmBody    = 0.50;     // Min 1m confirm body
input int      InpConfirmTimeoutMin = 120;      // Cancel setup after N minutes

input group "=== Exits ==="
input double   InpPartialPct        = 40.0;     // % close at T1 and T2
input bool     InpTradeEnabled      = true;     // false = signals only (Journal)

CTrade trade;
datetime g_last_m1_bar = 0;
datetime g_last_pattern_bar = 0;

// Pending pattern state
bool     g_pending = false;
int      g_side = 0;              // 1 = buy, -1 = sell
datetime g_pattern_time = 0;
double   g_pattern_high = 0;
double   g_pattern_low = 0;
double   g_target_step = 0;
bool     g_break_seen = false;

// Position management
int      g_targets_hit = 0;
double   g_entry_price = 0;
double   g_t1 = 0, g_t2 = 0, g_t3 = 0;
ulong    g_position_ticket = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);
   Print("HammerShootingStar EA started on ", _Symbol,
         " patternTF=", EnumToString(InpPatternTF),
         " lots=", InpLots,
         " trade=", InpTradeEnabled);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   ManageOpenPosition();

   datetime m1_time = iTime(_Symbol, PERIOD_M1, 0);
   if(m1_time == 0 || m1_time == g_last_m1_bar)
      return;
   // New M1 bar just opened → previous bar (index 1) is closed
   g_last_m1_bar = m1_time;

   // Detect new closed pattern bar
   datetime pt = iTime(_Symbol, InpPatternTF, 1);
   if(pt != 0 && pt != g_last_pattern_bar)
   {
      g_last_pattern_bar = pt;
      if(!PositionOpen() && !g_pending)
         ScanPatternBar();
   }

   if(g_pending && !PositionOpen())
      TryConfirmEntry();

   UpdateComment();
}

//+------------------------------------------------------------------+
bool PositionOpen()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!PositionSelectByTicket(PositionGetTicket(i)))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool SelectOurPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      g_position_ticket = ticket;
      return true;
   }
   g_position_ticket = 0;
   return false;
}

//+------------------------------------------------------------------+
double CandleBody(const ENUM_TIMEFRAMES tf, const int shift)
{
   return MathAbs(iClose(_Symbol, tf, shift) - iOpen(_Symbol, tf, shift));
}

//+------------------------------------------------------------------+
bool IsHammer(const int shift)
{
   double o = iOpen(_Symbol, InpPatternTF, shift);
   double h = iHigh(_Symbol, InpPatternTF, shift);
   double l = iLow(_Symbol, InpPatternTF, shift);
   double c = iClose(_Symbol, InpPatternTF, shift);
   double body = MathAbs(c - o);
   double upper = h - MathMax(o, c);
   double lower = MathMin(o, c) - l;
   double range = h - l;
   if(range < InpMinPatternPoints)
      return false;
   if(body <= 0)
      return (lower >= 0.55 * range && upper <= 0.15 * range);
   return (lower >= InpMinShadowRatio * body && upper <= body);
}

//+------------------------------------------------------------------+
bool IsShootingStar(const int shift)
{
   double o = iOpen(_Symbol, InpPatternTF, shift);
   double h = iHigh(_Symbol, InpPatternTF, shift);
   double l = iLow(_Symbol, InpPatternTF, shift);
   double c = iClose(_Symbol, InpPatternTF, shift);
   double body = MathAbs(c - o);
   double upper = h - MathMax(o, c);
   double lower = MathMin(o, c) - l;
   double range = h - l;
   if(range < InpMinPatternPoints)
      return false;
   if(body <= 0)
      return (upper >= 0.55 * range && lower <= 0.15 * range);
   return (upper >= InpMinShadowRatio * body && lower <= body);
}

//+------------------------------------------------------------------+
bool IsDowntrend(const int shift)
{
   if(Bars(_Symbol, InpPatternTF) < shift + InpTrendLookback + 2)
      return false;
   double sum = 0;
   for(int i = shift + 1; i <= shift + InpTrendLookback; i++)
      sum += iClose(_Symbol, InpPatternTF, i);
   double avg = sum / InpTrendLookback;
   double cur = iClose(_Symbol, InpPatternTF, shift);
   double prev = iClose(_Symbol, InpPatternTF, shift + 1);
   return (cur < avg && cur <= prev);
}

//+------------------------------------------------------------------+
bool IsUptrend(const int shift)
{
   if(Bars(_Symbol, InpPatternTF) < shift + InpTrendLookback + 2)
      return false;
   double sum = 0;
   for(int i = shift + 1; i <= shift + InpTrendLookback; i++)
      sum += iClose(_Symbol, InpPatternTF, i);
   double avg = sum / InpTrendLookback;
   double cur = iClose(_Symbol, InpPatternTF, shift);
   double prev = iClose(_Symbol, InpPatternTF, shift + 1);
   return (cur > avg && cur >= prev);
}

//+------------------------------------------------------------------+
void ScanPatternBar()
{
   const int sh = 1; // last closed pattern bar
   if(IsHammer(sh) && IsDowntrend(sh))
   {
      double high = iHigh(_Symbol, InpPatternTF, sh);
      double low  = iLow(_Symbol, InpPatternTF, sh) - InpSlBuffer;
      double risk = high - low;
      if(risk <= 0)
         return;
      ArmPending(1, iTime(_Symbol, InpPatternTF, sh), high, low, InpTargetPoints);
      Print("HAMMER pending BUY | high=", high, " SL=", low, " step=", InpTargetPoints);
      return;
   }
   if(IsShootingStar(sh) && IsUptrend(sh))
   {
      double high = iHigh(_Symbol, InpPatternTF, sh) + InpSlBuffer;
      double low  = iLow(_Symbol, InpPatternTF, sh);
      double risk = high - low;
      if(risk <= 0)
         return;
      ArmPending(-1, iTime(_Symbol, InpPatternTF, sh), high, low, InpTargetPoints);
      Print("SHOOTING STAR pending SELL | low=", low, " SL=", high, " step=", InpTargetPoints);
   }
}

//+------------------------------------------------------------------+
void ArmPending(const int side, const datetime t, const double hi, const double lo, const double step)
{
   g_pending = true;
   g_side = side;
   g_pattern_time = t;
   g_pattern_high = hi;
   g_pattern_low = lo;
   g_target_step = step;
   g_break_seen = false;
}

//+------------------------------------------------------------------+
void ClearPending()
{
   g_pending = false;
   g_side = 0;
   g_break_seen = false;
}

//+------------------------------------------------------------------+
void TryConfirmEntry()
{
   // Timeout
   if((TimeCurrent() - g_pattern_time) > InpConfirmTimeoutMin * 60)
   {
      Print("Pending cancelled: timeout");
      ClearPending();
      return;
   }

   // Closed 1m bar = shift 1
   double o = iOpen(_Symbol, PERIOD_M1, 1);
   double h = iHigh(_Symbol, PERIOD_M1, 1);
   double l = iLow(_Symbol, PERIOD_M1, 1);
   double c = iClose(_Symbol, PERIOD_M1, 1);
   double body = MathAbs(c - o);

   if(g_side > 0)
   {
      if(c < g_pattern_low)
      {
         Print("Pending BUY invalidated");
         ClearPending();
         return;
      }
      if(h > g_pattern_high)
         g_break_seen = true;
      if(!g_break_seen)
         return;
      if(!(c > o && c > g_pattern_high && body >= InpMinConfirmBody))
         return;
      EnterTrade(ORDER_TYPE_BUY, c, g_pattern_low);
   }
   else if(g_side < 0)
   {
      if(c > g_pattern_high)
      {
         Print("Pending SELL invalidated");
         ClearPending();
         return;
      }
      if(l < g_pattern_low)
         g_break_seen = true;
      if(!g_break_seen)
         return;
      if(!(c < o && c < g_pattern_low && body >= InpMinConfirmBody))
         return;
      EnterTrade(ORDER_TYPE_SELL, c, g_pattern_high);
   }
}

//+------------------------------------------------------------------+
void EnterTrade(const ENUM_ORDER_TYPE type, const double entry_ref, const double sl)
{
   double step = g_target_step;
   double entry = (type == ORDER_TYPE_BUY) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                           : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   g_entry_price = entry;
   if(type == ORDER_TYPE_BUY)
   {
      g_t1 = entry + step;
      g_t2 = entry + 2 * step;
      g_t3 = entry + 3 * step;
   }
   else
   {
      g_t1 = entry - step;
      g_t2 = entry - 2 * step;
      g_t3 = entry - 3 * step;
   }
   g_targets_hit = 0;

   PrintFormat("ENTRY %s @ %.5f SL=%.5f T1=%.5f T2=%.5f T3=%.5f",
               (type == ORDER_TYPE_BUY ? "BUY" : "SELL"),
               entry, sl, g_t1, g_t2, g_t3);

   if(!InpTradeEnabled)
   {
      Print("TradeEnabled=false — signal only");
      ClearPending();
      return;
   }

   bool ok = false;
   if(type == ORDER_TYPE_BUY)
      ok = trade.Buy(InpLots, _Symbol, entry, sl, g_t1, "Hammer");
   else
      ok = trade.Sell(InpLots, _Symbol, entry, sl, g_t1, "ShootingStar");

   if(!ok)
   {
      Print("Order failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
      return;
   }
   ClearPending();
   SelectOurPosition();
}

//+------------------------------------------------------------------+
void ManageOpenPosition()
{
   if(!SelectOurPosition())
   {
      g_targets_hit = 0;
      return;
   }

   long ptype = PositionGetInteger(POSITION_TYPE);
   double vol = PositionGetDouble(POSITION_VOLUME);
   double sl  = PositionGetDouble(POSITION_SL);
   double tp  = PositionGetDouble(POSITION_TP);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   // Rebuild ladder if EA restarted mid-trade
   if(g_entry_price <= 0)
   {
      g_entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
      double step = InpTargetPoints;
      if(ptype == POSITION_TYPE_BUY)
      {
         g_t1 = g_entry_price + step;
         g_t2 = g_entry_price + 2 * step;
         g_t3 = g_entry_price + 3 * step;
      }
      else
      {
         g_t1 = g_entry_price - step;
         g_t2 = g_entry_price - 2 * step;
         g_t3 = g_entry_price - 3 * step;
      }
   }

   bool hit = false;
   double next_level = (g_targets_hit == 0 ? g_t1 : (g_targets_hit == 1 ? g_t2 : g_t3));
   if(ptype == POSITION_TYPE_BUY && bid >= next_level)
      hit = true;
   if(ptype == POSITION_TYPE_SELL && ask <= next_level)
      hit = true;
   if(!hit)
      return;

   int level = g_targets_hit + 1;
   if(level >= 3)
   {
      if(trade.PositionClose(g_position_ticket))
         Print("T3 hit — closed all");
      g_targets_hit = 0;
      g_entry_price = 0;
      return;
   }

   double close_vol = NormalizeDouble(vol * InpPartialPct / 100.0, 2);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(close_vol < vmin)
      close_vol = vmin;
   // Keep at least one step open if possible
   if(vol - close_vol < vmin)
      close_vol = vol;

   if(!trade.PositionClosePartial(g_position_ticket, close_vol))
   {
      Print("Partial close failed: ", trade.ResultRetcodeDescription());
      return;
   }

   g_targets_hit = level;
   double new_sl, new_tp;
   if(level == 1)
   {
      new_sl = (g_entry_price + g_t1) / 2.0;
      new_tp = g_t2;
   }
   else
   {
      new_sl = g_t1;
      new_tp = g_t3;
   }
   trade.PositionModify(g_position_ticket, new_sl, new_tp);
   PrintFormat("T%d booked %.2f lots | new SL=%.5f TP=%.5f", level, close_vol, new_sl, new_tp);
}

//+------------------------------------------------------------------+
void UpdateComment()
{
   string s = "Hammer/ShootingStar EA (PDMBulls local)\n";
   s += "Symbol: " + _Symbol + " | Pattern TF: " + EnumToString(InpPatternTF) + "\n";
   s += "Lots: " + DoubleToString(InpLots, 2) + " | Trade: " + (InpTradeEnabled ? "ON" : "SIGNAL ONLY") + "\n";
   if(g_pending)
      s += StringFormat("PENDING %s | break=%s | SL=%.2f step=%.2f\n",
                        (g_side > 0 ? "BUY" : "SELL"),
                        (g_break_seen ? "yes" : "no"),
                        (g_side > 0 ? g_pattern_low : g_pattern_high),
                        g_target_step);
   if(SelectOurPosition())
      s += StringFormat("OPEN | targets_hit=%d | T1=%.2f T2=%.2f T3=%.2f\n",
                        g_targets_hit, g_t1, g_t2, g_t3);
   Comment(s);
}
//+------------------------------------------------------------------+
