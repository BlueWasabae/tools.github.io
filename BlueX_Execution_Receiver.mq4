//+------------------------------------------------------------------+
//|                                   BlueX_Execution_Receiver.mq4   |
//|                        LS Trading Academy / Quantitative Engine   |
//|               Institutional Supply & Demand Execution Receiver   |
//+------------------------------------------------------------------+
#property copyright "LS Trading Academy"
#property link      "https://bluex.academy"
#property version   "2.00"
#property strict

//--- Input Parameters
input string   InpBridgeUrl         = "http://127.0.0.1:8000/mt4/poll"; // Bridge Polling URL
input string   InpSecretKey         = "BLUEX_QUANT_SECURE_TOKEN_9981";  // Authentication Secret
input int      InpPollIntervalMs    = 500;                              // Polling Interval (ms)
input double   InpDefaultRiskPct    = 1.0;                              // Risk Percent per Trade
input int      InpSlippage          = 30;                               // Max Slippage (points)
input int      InpMagicNumber       = 880101;                           // Magic Number
input double   InpMaxSpreadPoints   = 50.0;                             // Max Spread Filter (points)

//--- Global Variables
datetime g_last_poll_time = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   EventSetMillisecondTimer(InpPollIntervalMs);
   Print("[BlueX Receiver] Initialized. Polling bridge at: ", InpBridgeUrl);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("[BlueX Receiver] Deinitialized. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Timer event handler                                              |
//+------------------------------------------------------------------+
void OnTimer()
{
   PollBridge();
}

//+------------------------------------------------------------------+
//| Poll Local Webhook Bridge for TradingView Execution Alerts       |
//+------------------------------------------------------------------+
void PollBridge()
{
   string url = InpBridgeUrl + "?secret=" + InpSecretKey;
   string headers = "User-Agent: BlueX-MT4-Receiver\r\n";
   char post[], result[];
   string result_headers;
   int timeout = 500;

   ResetLastError();
   int res = WebRequest("GET", url, headers, timeout, post, result, result_headers);

   if(res == -1)
   {
      int err = GetLastError();
      if(err == 4060) // ERR_WEBREQUEST_NOT_ALLOWED
      {
         Print("[BlueX Error] WebRequest not allowed! Add '", InpBridgeUrl, "' to Tools -> Options -> Expert Advisors -> Allow WebRequest.");
      }
      return;
   }

   if(res == 200)
   {
      string json = CharArrayToString(result);
      if(StringFind(json, "\"orders\":[]") < 0 && StringFind(json, "\"orders\": [ ]") < 0)
      {
         ProcessOrdersJson(json);
      }
   }
}

//+------------------------------------------------------------------+
//| Extract string value from flat JSON token                        |
//+------------------------------------------------------------------+
string ExtractJsonString(string json, string key)
{
   string search = "\"" + key + "\":\"";
   int start = StringFind(json, search);
   if(start < 0) return "";
   start += StringLen(search);
   int end = StringFind(json, "\"", start);
   if(end < 0) return "";
   return StringSubstr(json, start, end - start);
}

//+------------------------------------------------------------------+
//| Extract double value from flat JSON token                        |
//+------------------------------------------------------------------+
double ExtractJsonDouble(string json, string key)
{
   string search = "\"" + key + "\":";
   int start = StringFind(json, search);
   if(start < 0) return 0.0;
   start += StringLen(search);
   
   // Skip spaces
   while(StringSubstr(json, start, 1) == " ") start++;

   int end = start;
   while(end < StringLen(json))
   {
      string ch = StringSubstr(json, end, 1);
      if(ch == "," || ch == "}" || ch == "]" || ch == "\n" || ch == "\r") break;
      end++;
   }
   return StringToDouble(StringSubstr(json, start, end - start));
}

//+------------------------------------------------------------------+
//| Calculate Lot Size based on Fractional Account Risk              |
//+------------------------------------------------------------------+
double CalculateLots(string sym, double entry, double sl, double risk_pct)
{
   double equity = AccountEquity();
   double cash_risk = equity * (risk_pct / 100.0);
   double price_delta = MathAbs(entry - sl);
   if(price_delta <= 0) return MarketInfo(sym, MODE_MINLOT);

   double tick_size = MarketInfo(sym, MODE_TICKSIZE);
   double tick_value = MarketInfo(sym, MODE_TICKVALUE);
   if(tick_size <= 0) tick_size = 0.01;
   if(tick_value <= 0) tick_value = 1.0;

   double points_risk = price_delta / tick_size;
   double cost_per_lot = points_risk * tick_value;
   if(cost_per_lot <= 0) cost_per_lot = 1.0;

   double raw_lots = cash_risk / cost_per_lot;
   double lot_step = MarketInfo(sym, MODE_LOTSTEP);
   double min_lot = MarketInfo(sym, MODE_MINLOT);
   double max_lot = MarketInfo(sym, MODE_MAXLOT);

   double final_lots = MathFloor(raw_lots / lot_step) * lot_step;
   if(final_lots < min_lot) final_lots = min_lot;
   if(final_lots > max_lot) final_lots = max_lot;

   return NormalizeDouble(final_lots, 2);
}

//+------------------------------------------------------------------+
//| Parse and Execute Dispatched Order Payload                       |
//+------------------------------------------------------------------+
void ProcessOrdersJson(string json)
{
   Print("[BlueX Receiver] Raw JSON Payload: ", json);

   string action = ExtractJsonString(json, "action");
   string sym = ExtractJsonString(json, "symbol");
   if(sym == "" || sym == "XAUUSD") sym = Symbol();

   double entry = ExtractJsonDouble(json, "entry");
   double sl = ExtractJsonDouble(json, "sl");
   double tp1 = ExtractJsonDouble(json, "tp1");
   double risk_pct = ExtractJsonDouble(json, "risk_pct");
   if(risk_pct <= 0) risk_pct = InpDefaultRiskPct;

   // Spread check
   double spread = (MarketInfo(sym, MODE_ASK) - MarketInfo(sym, MODE_BID)) / MarketInfo(sym, MODE_POINT);
   if(spread > InpMaxSpreadPoints)
   {
      Print("[BlueX Rejected] Spread ", spread, " exceeds limit of ", InpMaxSpreadPoints);
      return;
   }

   if(action == "CANCEL" || action == "CANCEL_ALL")
   {
      CancelPendingOrders(sym);
      return;
   }

   if(action == "CLOSE_ALL")
   {
      CloseAllPositions(sym);
      return;
   }

   if(entry <= 0)
   {
      entry = (action == "BUY") ? MarketInfo(sym, MODE_ASK) : MarketInfo(sym, MODE_BID);
   }

   double lots = CalculateLots(sym, entry, sl, risk_pct);
   int cmd = -1;
   color arrow_col = clrGreen;

   if(action == "BUY")             cmd = OP_BUY;
   else if(action == "SELL")       { cmd = OP_SELL; arrow_col = clrRed; }
   else if(action == "BUY_LIMIT")  cmd = OP_BUYLIMIT;
   else if(action == "SELL_LIMIT") { cmd = OP_SELLLIMIT; arrow_col = clrRed; }
   else
   {
      Print("[BlueX Error] Unknown Action: ", action);
      return;
   }

   int ticket = OrderSend(sym, cmd, lots, entry, InpSlippage, sl, tp1, "BlueX Institutional", InpMagicNumber, 0, arrow_col);
   if(ticket < 0)
   {
      Print("[BlueX Execution Failed] Error: ", GetLastError());
   }
   else
   {
      Print("[BlueX Execution Success] Ticket #", ticket, " | Action: ", action, " | Lots: ", lots, " | Entry: ", entry, " | SL: ", sl, " | TP: ", tp1);
   }
}

//+------------------------------------------------------------------+
//| Cancel All Active Limit Orders                                   |
//+------------------------------------------------------------------+
void CancelPendingOrders(string sym)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == sym && OrderMagicNumber() == InpMagicNumber)
         {
            int type = OrderType();
            if(type == OP_BUYLIMIT || type == OP_SELLLIMIT || type == OP_BUYSTOP || type == OP_SELLSTOP)
            {
               OrderDelete(OrderTicket());
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Close All Open Positions                                         |
//+------------------------------------------------------------------+
void CloseAllPositions(string sym)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         if(OrderSymbol() == sym && OrderMagicNumber() == InpMagicNumber)
         {
            int type = OrderType();
            if(type == OP_BUY)
               OrderClose(OrderTicket(), OrderLots(), MarketInfo(sym, MODE_BID), InpSlippage, clrWhite);
            else if(type == OP_SELL)
               OrderClose(OrderTicket(), OrderLots(), MarketInfo(sym, MODE_ASK), InpSlippage, clrWhite);
         }
      }
   }
}
//+------------------------------------------------------------------+
