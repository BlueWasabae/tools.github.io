# BlueX Institutional Execution Cockpit & MT5 Bridge
**Operator:** Limeng Sovann | **Organization:** BlueX / LS Trading Academy  
**Repository:** [https://github.com/BlueWasabae/tools.github.io](https://github.com/BlueWasabae/tools.github.io)

---

## 1. System Architecture

The BlueX Institutional Execution Suite bridges real-time quantitative market structure analysis on TradingView with high-frequency, multi-account trade routing on MetaTrader 5 (MT5).

```
+-----------------------------------------------------------------------------------+
|                            TRADINGVIEW CHART ENGINE                               |
|   - Pine Script v5 Engine (Non-Repainting, barstate.isconfirmed)                  |
|   - Mechanical BOS / CHoCH Mapping                                               |
|   - Institutional Supply & Demand Zones (DBR, RBD, RBR, DBD)                     |
|   - Dynamic ATR & Spread Expansion Buffering                                      |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          | Parameterized Webhook Alert
                                          v
+-----------------------------------------------------------------------------------+
|                        FASTAPI EXECUTION BRIDGE (`server.py`)                     |
|   - Port 8000 (Local / Cloudflare Tunnel / Public Webhook)                        |
|   - Auth Guard (bluewasabae session token)                                        |
|   - Signal Approval & Invalidation Filter Pipeline                                |
|   - Dynamic Risk Engine (0.25% - 5.0% fractional account equity sizing)           |
|   - Multi-Account MT5 Router (`account_manager.py`)                              |
+--------------------+------------------------------------+-------------------------+
                     |                                    |
                     v                                    v
+-----------------------------------+    +------------------------------------------+
|      WEB COCKPIT FRONTEND         |    |        METATRADER 5 PYTHON CORE          |
|  - ShadCN / NextJS Admin Style    |    |  - `mt5_engine.py` (Official MetaTrader5)|
|  - Live SSE Floating Telemetry    |    |  - Multi-Terminal IPC Connection         |
|  - Approve / Decline Signal Cards |    |  - Exact Limit Order Injection           |
|  - Live Holding Positions Panel   |    |  - Programmatic SL/TP Step Modification  |
|  - 21st.dev ShadCN Trade Journal  |    |  - Auto-BE Engine @ +2.0 RR Gain         |
|  - Single-Account Filter & Stats  |    |  - 100% Verified Deal History Telemetry  |
+-----------------------------------+    +------------------------------------------+
```

---

## 2. Key Modules & Directory Structure

```
tools.github.io/
|-- index.html                              # Web Cockpit Frontend (ShadCN Sales Dashboard)
|-- journal.html                            # 21st.dev Full-Screen Calendar Trade Journal
|-- login.html                              # Authentication Gateway
|-- server.py                               # FastAPI Telemetry & Order Execution Server
|-- mt5_engine.py                           # MetaTrader 5 IPC Engine & Position Controller
|-- account_manager.py                      # Multi-Account MT5 Vault & Credentials Store
|-- config.py                               # Bridge Environment & Port Configurations
|-- bluex_institutional_cockpit_engine.pine  # Pine Script v5 Cockpit Webhook Indicator
|-- bluex_institutional_engine.pine          # Pine Script v5 Core Structural Indicator
|-- BlueX_Execution_Receiver.mq4            # Fallback MQL4 Receiver
|-- requirements.txt                        # Python Dependencies
|-- run_bridge.bat                          # Automated Local Bridge Launcher
|-- setup_tunnel.bat                        # Cloudflare Webhook Tunnel Exposer
`-- static/                                 # UI Static Mirror for Local FastAPI Serving
```

---

## 3. Core Capabilities

### A. Signal Ingestion & Semi-Automated Execution
- Ingests incoming institutional setups from Pine Script v5 via JSON webhooks.
- Generates structured pending signal cards displaying the exact S&D zone, refined Limit Entry, Invalidation Stop-Loss, and Target Liquidity Pools (TP1 / TP2).
- Operators can execute via 1-click **Approve** (injecting exact limit orders with dynamic fractional lot sizing) or **Decline**.

### B. Live Holding Positions Interactive Panel
- Real-time floating PnL, floating RR progress meters, and dynamic lot allocation.
- In-panel SL/TP step modification (`-` / `+` / `SET`) directly reflected in MT5.
- Instant 1-click **Move to Break-Even (BE)** and **Partial Close** controls.
- Global **Emergency Flatten** (Close All Positions).

### C. Mechanical Auto-BE @ +2.0 RR
- Autonomous background monitor tracks real-time tick prices.
- When an open position reaches or exceeds $+2.0\text{ R}$ profit relative to initial risk, the engine automatically moves the Stop-Loss to entry price $+\text{spread buffer}$.

### D. Single-Account Filtered Trade Journal
- Powered by the 21st.dev full-screen calendar UI.
- Filters real deal records for individual MT5 accounts directly from MT5 deal logs (`mt5.history_deals_get()`).
- Computes verified total profit, total loss, net monetary PnL, and accurate win-rate percentages.

---

## 4. Quickstart Guide

### Step 1: Install Python Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Configure MT5 Accounts
Open `account_manager.py` or edit `mt5_accounts.json` with your MT5 account credentials:
```json
[
  {
    "account_id": "115076007",
    "server": "MetaQuotes-Demo",
    "password": "your_password",
    "risk_percent": 1.0,
    "enabled": true
  }
]
```

### Step 3: Launch the Execution Bridge
Double-click `run_bridge.bat` or run:
```bash
python server.py
```
Access the Cockpit UI locally at: `http://127.0.0.1:8000/dashboard/sales`  
Sign in with operator credentials:
- **Username:** `bluewasabae`
- **Password:** `Bigduck009!`

### Step 4: Expose Webhook for TradingView
Double-click `setup_tunnel.bat` or launch a Cloudflare Tunnel:
```bash
cloudflared tunnel --url http://127.0.0.1:8000
```
Set your TradingView alert webhook URL to: `https://<your-tunnel>.trycloudflare.com/api/webhook/signal`.

---

## 5. Security & Risk Protocol
- Default fractional equity risk: $0.5\% - 1.0\%$ per execution.
- Minimum Risk-to-Reward ratio: $1:3\text{ RR}$.
- All modifications strictly validate minimum stop levels (`SYMBOL_TRADE_STOPS_LEVEL`) to eliminate server rejection.
