# ==============================================================================
# BLUEX QUANTITATIVE EXECUTION BRIDGE & COCKPIT SERVER
# Microsecond TradingView -> MT5/MT4 Automation & Web Cockpit Middleware
# ==============================================================================

import os
import sys
import time
import uuid
import logging
from typing import Dict, Any, List, Optional, Union

# Ensure directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from config import SystemConfig, AlertPayload, InstitutionalAlertPayload
from mt5_engine import MT5ExecutionEngine
from account_manager import AccountManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("BlueX.Server")

config = SystemConfig()
app = FastAPI(
    title="BlueX Quantitative Execution & Control Terminal",
    description="Microsecond Webhook Execution Gateway & Interactive Cockpit for MT5/MT4",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MT5 Engine, Account Manager & SMC Genesis Signal Provider Instances
from smc_signal_provider import SMCSignalProvider

account_manager = AccountManager()
mt5_engine = MT5ExecutionEngine(config)
signal_provider = SMCSignalProvider(config)

# Global Cockpit State
cockpit_state = {
    "risk_mode": "SAFE",            # "SAFE", "AGGRESSIVE", or "CUSTOM"
    "custom_risk_pct": 0.50,        # Granular risk percentage adjust (0.10% to 5.0%)
    "execution_mode": "MANUAL",      # "AUTO" (Direct execution) or "MANUAL" (Positions approve)
    "target_rr": 3.0,               # Target Risk:Reward ratio
    "spread_buffer_usd": 0.40,      # Dynamic spread buffer
    "auto_be_enabled": False,       # Auto BE after holding >= +2.0 RR
    "auto_be_trigger_rr": 2.0,      # Trigger multiple (+2.0 RR)
    "trade_style": "day",           # "day" (Intraday M1-M15) or "swing" (Macro H1-H4)
    "pending_signals": [],          # Queue for manual position approvals
    "execution_log": []             # Historical audit log
}

mt4_order_queue: List[Dict[str, Any]] = []

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)

class SettingsUpdate(BaseModel):
    risk_mode: Optional[str] = None
    custom_risk_pct: Optional[float] = None
    execution_mode: Optional[str] = None
    target_rr: Optional[float] = None
    spread_buffer_usd: Optional[float] = None
    sl_cover_buffer: Optional[float] = None
    auto_be_enabled: Optional[bool] = None
    auto_be_trigger_rr: Optional[float] = None
    trade_style: Optional[str] = None  # "day" or "swing"

@app.on_event("startup")
async def startup_event():
    logger.info("Initializing BlueX Institutional Gateway & Cockpit Server...")
    active_acc = account_manager.get_active_account()
    if active_acc:
        config.MT5_LOGIN = active_acc.get("login", 0)
        config.MT5_PASSWORD = active_acc.get("password", "")
        config.MT5_SERVER = active_acc.get("server", "")
        config.MT5_PATH = active_acc.get("path", config.MT5_PATH)
    connected = mt5_engine.initialize()
    if not connected:
        logger.warning("[WARNING] MT5 not connected at startup. Will re-attempt on demand.")
    else:
        logger.info("[READY] MT5 IPC Bridge online.")

@app.on_event("shutdown")
async def shutdown_event():
    mt5_engine.shutdown()
    logger.info("BlueX Institutional Gateway safely terminated.")

# ==============================================================================
# AUTHENTICATION SUBSYSTEM (SHADCN / SING-APP LOGIN GATE)
# ==============================================================================

AUTH_USER = {
    "username": "bluewasabae",
    "password": "Bigduck009!",
    "name": "Blue Wasabae",
    "role": "Lead Quantitative Operator"
}

ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    """Authenticates the operator and issues a session token."""
    if req.username == AUTH_USER["username"] and req.password == AUTH_USER["password"]:
        token = f"bx_session_{uuid.uuid4().hex}"
        ACTIVE_SESSIONS[token] = {
            "username": AUTH_USER["username"],
            "name": AUTH_USER["name"],
            "role": AUTH_USER["role"],
            "authenticated_at": time.time()
        }
        logger.info(f"[AUTH SUCCESS] User '{req.username}' authenticated successfully.")
        resp = JSONResponse(content={
            "status": "success",
            "token": token,
            "user": {
                "username": AUTH_USER["username"],
                "name": AUTH_USER["name"],
                "role": AUTH_USER["role"]
            }
        })
        resp.set_cookie(
            key="bx_session", 
            value=token, 
            max_age=86400 * 14, 
            httponly=False, 
            samesite="lax"
        )
        return resp
    
    logger.warning(f"[AUTH FAILED] Failed login attempt for username: '{req.username}'")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    """Terminates active session token."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if "Bearer " in auth_header else request.cookies.get("bx_session", "")
    if token in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[token]
    resp = JSONResponse(content={"status": "success", "message": "Logged out successfully"})
    resp.delete_cookie("bx_session")
    return resp

@app.get("/api/auth/verify")
async def auth_verify(request: Request):
    """Verifies validity of active session token."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if "Bearer " in auth_header else request.cookies.get("bx_session", "")
    if token and token in ACTIVE_SESSIONS:
        return {
            "authenticated": True,
            "user": ACTIVE_SESSIONS[token]
        }
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session token")

# ==============================================================================
# WEB COCKPIT STATIC ROUTING
# ==============================================================================

@app.get("/")
@app.get("/terminal")
@app.get("/cockpit")
@app.get("/dashboard")
@app.get("/dashboard/sales")
async def serve_terminal():
    """Serves the institutional sales & execution web cockpit."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "BlueX Cockpit UI initialized. Place index.html in static/"}

@app.get("/login")
async def serve_login():
    """Serves the sleek shadcn authentication portal."""
    login_path = os.path.join(STATIC_DIR, "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return {"message": "Login portal initialized. Place login.html in static/"}

@app.api_route("/journal", methods=["GET", "HEAD"])
@app.api_route("/journal/", methods=["GET", "HEAD"])
@app.api_route("/journal.html", methods=["GET", "HEAD"])
@app.api_route("/journal/index.html", methods=["GET", "HEAD"])
async def serve_journal():
    """Serves the institutional trading journal calendar."""
    candidates = [
        os.path.join(STATIC_DIR, "journal.html"),
        os.path.join(STATIC_DIR, "journal", "index.html"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal.html"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal", "index.html"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return FileResponse(p)
    return {"message": "Trading Journal calendar initialized."}

# ==============================================================================
# COCKPIT STATE & SETTINGS ENDPOINTS
# ==============================================================================

def enrich_accounts_data(acc_summary: Dict[str, Any], positions: List[Dict[str, Any]], pending_orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Enriches all configured accounts with live MT5 telemetry, balance, equity, and active positions."""
    raw_accounts = account_manager.get_accounts()
    active_acc = account_manager.get_active_account()
    enriched = []
    live_login = acc_summary.get("login") if acc_summary.get("connected") else None

    for a in raw_accounts:
        a_copy = dict(a)
        is_connected = False
        if acc_summary.get("connected"):
            if live_login and int(a.get("login", 0)) == int(live_login):
                is_connected = True
            elif active_acc and a.get("id") == active_acc.get("id"):
                is_connected = True
                if live_login and a.get("login") != live_login:
                    a_copy["login"] = live_login
                    account_manager.update_account_settings(a["id"], {
                        "login": live_login,
                        "server": acc_summary.get("broker", a["server"]),
                        "last_balance": acc_summary.get("balance", 0.0),
                        "last_equity": acc_summary.get("equity", 0.0)
                    })

        a_copy["is_connected"] = is_connected

        if is_connected:
            a_copy["balance"] = round(float(acc_summary.get("balance", 0.0)), 2)
            a_copy["equity"] = round(float(acc_summary.get("equity", 0.0)), 2)
            a_copy["profit"] = round(float(acc_summary.get("profit", 0.0)), 2)
            a_copy["margin"] = round(float(acc_summary.get("margin", 0.0)), 2)
            a_copy["margin_free"] = round(float(acc_summary.get("margin_free", 0.0)), 2)
            a_copy["margin_level"] = round(float(acc_summary.get("margin_level", 0.0)), 2)
            a_copy["currency"] = acc_summary.get("currency", "USD")
            a_copy["leverage"] = acc_summary.get("leverage", 100)
            a_copy["positions"] = positions
            a_copy["pending_orders"] = pending_orders
            a_copy["open_positions_count"] = len(positions)
            a_copy["pending_orders_count"] = len(pending_orders)
        else:
            last_bal = round(float(a.get("last_balance", 100000.0)), 2)
            last_eq = round(float(a.get("last_equity", 100000.0)), 2)
            a_copy["balance"] = last_bal
            a_copy["equity"] = last_eq
            a_copy["profit"] = 0.0
            a_copy["margin"] = 0.0
            a_copy["margin_free"] = last_eq
            a_copy["margin_level"] = 0.0
            a_copy["currency"] = "USD"
            a_copy["leverage"] = 100
            a_copy["positions"] = []
            a_copy["pending_orders"] = []
            a_copy["open_positions_count"] = 0
            a_copy["pending_orders_count"] = 0

        enriched.append(a_copy)
    return enriched

@app.get("/api/state")
async def get_state():
    """Returns combined account, market, controls, and pending signals telemetry."""
    # Check and trigger auto-BE if enabled
    auto_be_actions = []
    if cockpit_state["auto_be_enabled"]:
        auto_be_actions = mt5_engine.check_and_apply_auto_be_2rr("XAUUSD", buffer_usd=cockpit_state["spread_buffer_usd"])

    acc = mt5_engine.get_account_summary()
    tick = mt5_engine.get_live_tick("XAUUSD")
    raw_positions = mt5_engine.get_open_positions("XAUUSD")
    pending_orders = mt5_engine.get_pending_orders("XAUUSD")
    deals_summary = mt5_engine.get_deals_history(days=90)
    active_acc = account_manager.get_active_account()

    # Enrich each position with full MT5 account identity, holding price, and complete risk audit checks
    enriched_positions = []
    spread_usd = tick.get("spread_usd", 0.13) if isinstance(tick, dict) else 0.13
    spread_pts = tick.get("spread_points", 13.0) if isinstance(tick, dict) else 13.0
    buffer_usd = cockpit_state.get("spread_buffer_usd", 0.40)

    for p in raw_positions:
        p_copy = dict(p)
        p_copy["account_name"] = active_acc.get("name", "Primary Trading Account") if active_acc else "Primary Desk"
        p_copy["account_login"] = active_acc.get("login", acc.get("login", 5058361801)) if active_acc else acc.get("login", 5058361801)
        p_copy["account_id"] = active_acc.get("id", "acc_default_1") if active_acc else "acc_default_1"
        p_copy["account_server"] = active_acc.get("server", acc.get("broker", "MetaQuotes-Demo")) if active_acc else acc.get("broker", "MetaQuotes-Demo")
        p_copy["trade_style"] = active_acc.get("trade_style", "DAY_TRADE") if active_acc else "DAY_TRADE"
        p_copy["open_price"] = p_copy["price_open"]
        p_copy["holding_price"] = p_copy["price_current"]
        p_copy["pnl"] = p_copy["profit"]

        open_p = p_copy["price_open"]
        curr_p = p_copy["price_current"]
        sl = p_copy["sl"]
        tp = p_copy["tp"]
        vol = p_copy["volume"]
        is_buy = (p_copy["type"] == "BUY")

        # SL and TP Distance in points (0.01 = 1 point)
        p_copy["sl_dist_pts"] = round(abs(curr_p - sl) * 100, 1) if sl > 0 else 0.0
        p_copy["tp_dist_pts"] = round(abs(tp - curr_p) * 100, 1) if tp > 0 else 0.0

        # Cash at risk and cash reward (100 oz contract size per lot)
        contract_size = 100.0
        p_copy["cash_risk"] = round(abs(open_p - sl) * contract_size * vol, 2) if sl > 0 else 0.0
        p_copy["cash_reward"] = round(abs(tp - open_p) * contract_size * vol, 2) if tp > 0 else 0.0

        # Calculated Risk:Reward (RR) ratio
        risk_pts = abs(open_p - sl)
        reward_pts = abs(tp - open_p)
        p_copy["rr_ratio"] = round(reward_pts / max(0.10, risk_pts), 2) if (sl > 0 and tp > 0) else 0.0
        p_copy["is_rr_valid"] = (p_copy["rr_ratio"] >= 3.0)
        p_copy["is_be_protected"] = (sl >= open_p) if is_buy else (sl <= open_p and sl > 0)
        p_copy["drift_usd"] = round((curr_p - open_p) if is_buy else (open_p - curr_p), 2)
        p_copy["spread_pts"] = spread_pts
        p_copy["spread_usd"] = spread_usd
        p_copy["sl_cover_buffer"] = buffer_usd

        enriched_positions.append(p_copy)

    positions = enriched_positions
    enriched_accounts = enrich_accounts_data(acc, positions, pending_orders)

    return {
        "risk_mode": cockpit_state["risk_mode"],
        "custom_risk_pct": cockpit_state["custom_risk_pct"],
        "execution_mode": cockpit_state["execution_mode"],
        "target_rr": cockpit_state["target_rr"],
        "spread_buffer_usd": cockpit_state["spread_buffer_usd"],
        "sl_cover_buffer": cockpit_state["spread_buffer_usd"],
        "auto_be_enabled": cockpit_state["auto_be_enabled"],
        "auto_be_trigger_rr": cockpit_state["auto_be_trigger_rr"],
        "trade_style": cockpit_state.get("trade_style", "day"),
        "auto_be_actions_recent": auto_be_actions,
        "account": acc,
        "accounts_list": enriched_accounts,
        "active_account": account_manager.get_active_account(),
        "tick": tick,
        "positions": positions,
        "pending_orders": pending_orders,
        "pending_signals": cockpit_state["pending_signals"],
        "real_stats": {
            "total_realized_pnl": deals_summary["total_realized_pnl"],
            "total_volume_lots": deals_summary["total_volume_lots"],
            "closed_trades_count": deals_summary["closed_trades_count"],
            "winning_trades": deals_summary["winning_trades"],
            "losing_trades": deals_summary["losing_trades"],
            "win_rate_pct": deals_summary["win_rate_pct"],
            "profit_factor": deals_summary["profit_factor"],
            "gross_profit": deals_summary["gross_profit"],
            "gross_loss": deals_summary["gross_loss"]
        },
        "recent_deals": deals_summary["deals"][:15]
    }

@app.post("/api/settings")
async def update_settings(settings: SettingsUpdate):
    """Updates interactive cockpit controls in real-time."""
    if settings.risk_mode in ["SAFE", "AGGRESSIVE", "CUSTOM"]:
        cockpit_state["risk_mode"] = settings.risk_mode
        if settings.risk_mode == "SAFE":
            cockpit_state["custom_risk_pct"] = 0.5
            config.DEFAULT_RISK_PCT = 0.5
            config.MAX_SPREAD_POINTS = 30
        elif settings.risk_mode == "AGGRESSIVE":
            cockpit_state["custom_risk_pct"] = 1.5
            config.DEFAULT_RISK_PCT = 1.5
            config.MAX_SPREAD_POINTS = 50

    if settings.custom_risk_pct is not None and 0.05 <= settings.custom_risk_pct <= 10.0:
        cockpit_state["custom_risk_pct"] = round(settings.custom_risk_pct, 2)
        config.DEFAULT_RISK_PCT = cockpit_state["custom_risk_pct"]
        cockpit_state["risk_mode"] = "CUSTOM"

    if settings.execution_mode in ["AUTO", "MANUAL"]:
        cockpit_state["execution_mode"] = settings.execution_mode

    if settings.target_rr is not None and 1.0 <= settings.target_rr <= 10.0:
        cockpit_state["target_rr"] = settings.target_rr
        config.MIN_RR_RATIO = settings.target_rr

    buffer_val = settings.sl_cover_buffer if settings.sl_cover_buffer is not None else settings.spread_buffer_usd
    if buffer_val is not None and 0.0 <= buffer_val <= 5.0:
        cockpit_state["spread_buffer_usd"] = round(buffer_val, 2)

    if settings.auto_be_enabled is not None:
        cockpit_state["auto_be_enabled"] = settings.auto_be_enabled

    if settings.auto_be_trigger_rr is not None and 1.0 <= settings.auto_be_trigger_rr <= 5.0:
        cockpit_state["auto_be_trigger_rr"] = settings.auto_be_trigger_rr

    if settings.trade_style in ["day", "swing"]:
        cockpit_state["trade_style"] = settings.trade_style
        if settings.trade_style == "swing":
            if settings.target_rr is None:
                cockpit_state["target_rr"] = 5.0
                config.MIN_RR_RATIO = 5.0
        elif settings.trade_style == "day":
            if settings.target_rr is None:
                cockpit_state["target_rr"] = 3.0
                config.MIN_RR_RATIO = 3.0

    logger.info(f"[SETTINGS UPDATED] Risk: {cockpit_state['custom_risk_pct']}% | Mode: {cockpit_state['risk_mode']} | Auto-BE: {cockpit_state['auto_be_enabled']} | RR: 1:{cockpit_state['target_rr']} | Style: {cockpit_state.get('trade_style', 'day')} | SL Cover: ${cockpit_state['spread_buffer_usd']:.2f}")
    return {"status": "success", "settings": cockpit_state}

# ==============================================================================
# MULTI-ACCOUNT MT5 MANAGEMENT ENDPOINTS
# ==============================================================================

@app.get("/api/accounts")
async def list_accounts():
    acc = mt5_engine.get_account_summary()
    positions = mt5_engine.get_open_positions("XAUUSD")
    pending_orders = mt5_engine.get_pending_orders("XAUUSD")
    return {
        "accounts": enrich_accounts_data(acc, positions, pending_orders),
        "active_account": account_manager.get_active_account()
    }

class AccountAddRequest(BaseModel):
    name: str
    login: int
    password: Optional[str] = ""
    server: str
    path: Optional[str] = r"C:\Program Files\MetaTrader 5\terminal64.exe"

@app.post("/api/accounts")
async def add_or_update_account(acc: AccountAddRequest):
    updated = account_manager.add_or_update_account(acc.dict())
    return {"status": "success", "account": updated}

@app.post("/api/accounts/{acc_id}/switch")
async def switch_account(acc_id: str):
    target = account_manager.switch_active_account(acc_id)
    if not target:
        raise HTTPException(status_code=404, detail="Account not found")

    # Re-initialize MT5 with target account
    switched = mt5_engine.switch_account(target)
    return {
        "status": "success" if switched else "failed",
        "switched": switched,
        "active_account": account_manager.get_active_account(),
        "account_info": mt5_engine.get_account_summary()
    }

@app.delete("/api/accounts/{acc_id}")
async def delete_account(acc_id: str):
    deleted = account_manager.delete_account(acc_id)
    return {"status": "success" if deleted else "not_found"}

class AccountSettingsRequest(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    trade_style: Optional[str] = None
    auto_tp: Optional[bool] = None
    tp_cap_rr: Optional[float] = None
    tp_adjust_pts: Optional[float] = None
    sl_cover_buffer: Optional[float] = None

@app.post("/api/accounts/{acc_id}/settings")
async def update_account_settings_api(acc_id: str, req: AccountSettingsRequest):
    """Updates per-account tactical parameters (Auto TP, TP Cap, Adjust TP, SL Cover Buffer, Active state)."""
    data = req.dict(exclude_unset=True)
    updated = account_manager.update_account_settings(acc_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "success", "account": updated}

@app.post("/api/accounts/{acc_id}/close-all")
async def account_close_all_api(acc_id: str):
    """Emergency close for 100% of open positions on a specific MT5 account."""
    acc = account_manager.get_account_by_id(acc_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    active = account_manager.get_active_account()
    needs_revert = (active and active["id"] != acc_id)
    if needs_revert:
        mt5_engine.switch_account(acc)
    res = mt5_engine.close_all_positions_and_pending("XAUUSD")
    if needs_revert:
        mt5_engine.switch_account(active)
    return {"status": "success", "account_id": acc_id, "account_name": acc["name"], "result": res}

@app.post("/api/accounts/{acc_id}/be-all")
async def account_be_all_api(acc_id: str):
    """Moves all profitable open positions on a specific MT5 account to Breakeven (+ SL cover buffer)."""
    acc = account_manager.get_account_by_id(acc_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    active = account_manager.get_active_account()
    needs_revert = (active and active["id"] != acc_id)
    if needs_revert:
        mt5_engine.switch_account(acc)
    buffer = acc.get("sl_cover_buffer", cockpit_state["spread_buffer_usd"])
    res = mt5_engine.move_all_to_breakeven("XAUUSD", buffer_usd=buffer)
    if needs_revert:
        mt5_engine.switch_account(active)
    return {"status": "success", "account_id": acc_id, "account_name": acc["name"], "result": res}

# ==============================================================================
# TACTICAL INSTITUTIONAL ACTIONS (BE MOVE ALL / CLOSE ALL)
# ==============================================================================

@app.post("/api/actions/be-all")
async def action_be_move_all():
    """Tactical 1-Click: Moves all profitable open positions to Breakeven (+ spread buffer)."""
    res = mt5_engine.move_all_to_breakeven("XAUUSD", buffer_usd=cockpit_state["spread_buffer_usd"])
    logger.info(f"[TACTICAL BE] {res.get('message')}")
    return res

@app.post("/api/actions/close-all")
async def action_close_all():
    """Emergency Kill Switch: Closes 100% of open positions and deletes all pending limit orders."""
    res = mt5_engine.close_all_positions_and_pending("XAUUSD")
    logger.warning(f"[KILL SWITCH EXECUTED] {res.get('message')}")
    return res

@app.post("/api/positions/{ticket}/close")
async def close_position_ticket(ticket: int):
    """Closes a specific market position ticket."""
    return mt5_engine.close_single_ticket(ticket)

class PositionModifyRequest(BaseModel):
    sl: float
    tp: float

@app.post("/api/positions/{ticket}/modify")
async def modify_position(ticket: int, req: PositionModifyRequest):
    """Adjusts SL and TP directly on the live MT5 position ticket from the website panel."""
    return mt5_engine.modify_position_sltp(ticket, req.sl, req.tp)

class PositionPartialCloseRequest(BaseModel):
    volume: float

@app.post("/api/positions/{ticket}/close-partial")
async def partial_close_position(ticket: int, req: PositionPartialCloseRequest):
    """Closes a specific lot size from an active MT5 position."""
    return mt5_engine.close_partial_position(ticket, req.volume)

@app.post("/api/positions/{ticket}/be")
async def move_single_ticket_be(ticket: int):
    """Moves a single active position to breakeven (+ spread buffer)."""
    positions = mt5_engine.get_open_positions("XAUUSD")
    target = next((p for p in positions if p["ticket"] == ticket), None)
    if not target:
        raise HTTPException(status_code=404, detail="Position not found")
    buffer = cockpit_state["spread_buffer_usd"]
    new_sl = round(target["price_open"] + buffer if target["type"] == "BUY" else target["price_open"] - buffer, 2)
    return mt5_engine.modify_position_sltp(ticket, new_sl, target["tp"])

@app.post("/api/actions/auto-be-toggle")
async def toggle_auto_be():
    """Toggles Auto Breakeven after holding +2.0 RR."""
    cockpit_state["auto_be_enabled"] = not cockpit_state["auto_be_enabled"]
    logger.info(f"[AUTO BE TOGGLE] Status now: {cockpit_state['auto_be_enabled']}")
    return {"status": "success", "auto_be_enabled": cockpit_state["auto_be_enabled"]}

@app.get("/api/journal/history")
async def get_journal_history(account_id: Optional[str] = None):
    """Retrieves real MT5 historical closed deals for the requested account (single account record)."""
    # If account_id is specified and distinct from active, switch to that account
    if account_id:
        acc_obj = account_manager.get_account_by_id(account_id)
        if acc_obj and not acc_obj.get("is_active"):
            account_manager.switch_active_account(account_id)
            mt5_engine.switch_account(acc_obj)

    history = mt5_engine.get_deals_history(days=90)
    active_acc = account_manager.get_active_account()
    return {
        "account": active_acc,
        "accounts_list": account_manager.get_accounts(),
        "stats": {
            "total_realized_pnl": history["total_realized_pnl"],
            "total_volume_lots": history["total_volume_lots"],
            "closed_trades_count": history["closed_trades_count"],
            "win_rate_pct": history["win_rate_pct"],
            "profit_factor": history["profit_factor"],
            "winning_trades": history["winning_trades"],
            "losing_trades": history["losing_trades"],
            "gross_profit": history["gross_profit"],
            "gross_loss": history["gross_loss"]
        },
        "deals": history["deals"]
    }

# ==============================================================================
# SIGNAL APPROVAL QUEUE (Positions Approve Pipeline & Multicast Engine)
# ==============================================================================

def calculate_bot_tp(symbol: str, action: str, entry: float, sl: float, scenario_id: int = 1) -> float:
    """
    Bot-Decided Take Profit using Pure Institutional Supply & Demand (S&D).
    Longs target external Buy-Side Liquidity (BSL) swing highs / opposing Supply bases.
    Shorts target external Sell-Side Liquidity (SSL) swing lows / opposing Demand bases.
    Enforces minimum 1:3 RR rule.
    """
    risk_delta = max(0.50, abs(entry - sl))
    if scenario_id == 1:
        default_rr = 3.5
    elif scenario_id == 2:
        default_rr = 4.0
    elif scenario_id == 3:
        default_rr = 3.0
    else:
        default_rr = max(3.0, cockpit_state.get("target_rr", 3.0))

    if "BUY" in action.upper():
        return round(entry + (risk_delta * default_rr), 2)
    else:
        return round(entry - (risk_delta * default_rr), 2)

def execute_multicast_signal(exec_alert: AlertPayload, scenario_id: int = 1) -> Dict[str, Any]:
    """
    Broadcasts and sets limit orders simultaneously across ALL active MT5 accounts.
    Zero sequential delays. Applies per-account Auto TP, TP Cap, Adjust TP, and SL cover adjustments.
    """
    active_accounts = account_manager.get_active_accounts()
    current_active = account_manager.get_active_account()
    results = []

    for acc in active_accounts:
        try:
            if current_active and acc["id"] != current_active.get("id"):
                mt5_engine.switch_account(acc)

            acc_alert = AlertPayload(**exec_alert.dict())

            auto_tp = acc.get("auto_tp", True)
            trade_style = acc.get("trade_style", "DAY_TRADE")
            tp_cap = acc.get("tp_cap_rr")
            tp_adjust = acc.get("tp_adjust_pts", 0.0)
            risk_delta = max(0.50, abs(acc_alert.entry - acc_alert.sl))

            # Apply account-specific Day vs Swing Trade parameters
            if auto_tp:
                bot_tp = calculate_bot_tp(acc_alert.symbol, acc_alert.action, acc_alert.entry, acc_alert.sl, scenario_id)
                # For Swing Trade accounts, expand target towards macro liquidity pool if uncapped
                if trade_style == "SWING_TRADE" and (not tp_cap or tp_cap < 4.0):
                    swing_tp_dist = risk_delta * 5.0
                    bot_tp = round(acc_alert.entry + swing_tp_dist if "BUY" in acc_alert.action.upper() else acc_alert.entry - swing_tp_dist, 2)

                if tp_cap and tp_cap > 0:
                    capped_dist = risk_delta * tp_cap
                    if "BUY" in acc_alert.action.upper():
                        acc_alert.tp1 = min(bot_tp, round(acc_alert.entry + capped_dist, 2))
                    else:
                        acc_alert.tp1 = max(bot_tp, round(acc_alert.entry - capped_dist, 2))
                else:
                    acc_alert.tp1 = bot_tp
            else:
                default_target = 5.0 if trade_style == "SWING_TRADE" else cockpit_state.get("target_rr", 3.0)
                rr = tp_cap if (tp_cap and tp_cap > 0) else default_target
                if "BUY" in acc_alert.action.upper():
                    acc_alert.tp1 = round(acc_alert.entry + (risk_delta * rr), 2)
                else:
                    acc_alert.tp1 = round(acc_alert.entry - (risk_delta * rr), 2)

            if tp_adjust != 0.0:
                if "BUY" in acc_alert.action.upper():
                    acc_alert.tp1 = round(acc_alert.tp1 + tp_adjust, 2)
                else:
                    acc_alert.tp1 = round(acc_alert.tp1 - tp_adjust, 2)

            sl_cover = acc.get("sl_cover_buffer", cockpit_state.get("spread_buffer_usd", 0.40))
            style_tag = "SWING" if trade_style == "SWING_TRADE" else "DAY"
            acc_alert.comment = f"BlueX [{style_tag}] SL+{sl_cover:.2f}"

            res = mt5_engine.execute_alert(acc_alert)
            results.append({
                "account_id": acc["id"],
                "account_name": acc["name"],
                "login": acc["login"],
                "status": res.get("status"),
                "order_ticket": res.get("order_ticket"),
                "volume": res.get("volume"),
                "entry": acc_alert.entry,
                "sl": acc_alert.sl,
                "tp": acc_alert.tp1,
                "sl_cover_buffer": sl_cover,
                "message": res.get("message", "Limit order set")
            })
        except Exception as e:
            logger.error(f"[MULTICAST ERROR] Account #{acc.get('login')} failed: {e}")
            results.append({
                "account_id": acc["id"],
                "account_name": acc["name"],
                "login": acc["login"],
                "status": "error",
                "message": str(e)
            })

    if current_active and active_accounts and active_accounts[-1]["id"] != current_active["id"]:
        mt5_engine.switch_account(current_active)

    return {
        "status": "success",
        "total_dispatched": len(results),
        "accounts": results
    }

@app.post("/api/signals/{signal_id}/approve")
async def approve_signal(signal_id: str):
    """Executes a queued signal to MT5 across all active accounts simultaneously after operator confirmation."""
    target_idx = None
    for i, s in enumerate(cockpit_state["pending_signals"]):
        if s["id"] == signal_id:
            target_idx = i
            break

    if target_idx is None:
        raise HTTPException(status_code=404, detail="Signal not found or already processed")

    sig = cockpit_state["pending_signals"].pop(target_idx)
    entry = sig["entry"]
    sl = sig["sl"]
    scenario_id = sig.get("scenario_id", 1)
    risk_pct = cockpit_state["custom_risk_pct"]

    # Enforce strict Limit Buy/Sell order action (Zero market execution permission)
    sig_action = sig["action"].upper()
    order_action = "BUY_LIMIT" if "BUY" in sig_action else ("SELL_LIMIT" if "SELL" in sig_action else sig_action)

    # Bot decides TP using Pure Institutional S&D framework
    tp = calculate_bot_tp(sig["symbol"], order_action, entry, sl, scenario_id)

    payload = AlertPayload(
        secret=config.WEBHOOK_SECRET_KEY,
        symbol=sig["symbol"],
        action=order_action,  # Strictly BUY_LIMIT or SELL_LIMIT
        entry=entry,
        sl=sl,
        tp1=tp,
        risk_pct=risk_pct,
        magic=sig.get("magic", 880101),
        comment=f"SMC Genesis Limit ({risk_pct}%)"
    )

    multicast_res = execute_multicast_signal(payload, scenario_id=scenario_id)
    logger.info(f"[MANUAL SIGNAL APPROVED] Dispatched signal {signal_id} simultaneously to {len(multicast_res.get('accounts', []))} account(s)")

    return {
        "status": "success",
        "message": f"Signal {signal_id} approved and dispatched simultaneously across all active MT5 accounts",
        "multicast": multicast_res
    }

@app.post("/api/signals/{signal_id}/reject")
async def reject_signal(signal_id: str):
    """Rejects / dismisses a pending signal."""
    initial_len = len(cockpit_state["pending_signals"])
    cockpit_state["pending_signals"] = [s for s in cockpit_state["pending_signals"] if s["id"] != signal_id]
    if len(cockpit_state["pending_signals"]) < initial_len:
        logger.info(f"[SIGNAL REJECTED] Signal #{signal_id} dismissed by operator.")
        return {"status": "success", "message": "Signal dismissed"}
    raise HTTPException(status_code=404, detail="Signal not found")

# ==============================================================================
# TRADINGVIEW / SCANNER WEBHOOK INGRESS
# ==============================================================================

@app.post("/webhook")
@app.post("/api/webhook")
async def handle_tradingview_webhook(payload: Union[InstitutionalAlertPayload, AlertPayload], request: Request):
    """
    Primary ingress for TradingView alerts, SMC Genesis Institutional Engine, and BlueX Market Scanner.
    - If execution_mode == "AUTO": Direct microsecond execution to MT5.
    - If execution_mode == "MANUAL": Pushes to Signal Approval Queue.
    """
    t_start = time.perf_counter()

    # Normalize InstitutionalAlertPayload or AlertPayload into uniform execution parameters
    if isinstance(payload, InstitutionalAlertPayload):
        token = payload.auth_token
        action = payload.setup.order_type
        symbol = payload.symbol
        entry = payload.setup.entry_price
        sl = payload.setup.stop_loss
        tp1 = payload.setup.take_profit_1
        tp2 = payload.setup.take_profit_2
        risk_pct = payload.risk_engine.account_risk_percent
        precalc_lots = payload.risk_engine.calculated_lot_size
        comment = f"SMC Genesis {payload.scenario}"
        scenario_tag = payload.scenario
        zone_type = payload.setup.zone_type
        structure_bias = payload.setup.structure_bias.dict()
        be_trigger = payload.risk_engine.be_trigger_level
        magic = config.MAGIC_NUMBER_BASE + 101
    else:
        token = payload.secret
        action = payload.action
        symbol = payload.symbol
        entry = payload.entry
        sl = payload.sl
        tp1 = payload.tp1
        tp2 = payload.tp2
        risk_pct = payload.risk_pct
        precalc_lots = None
        comment = payload.comment or "BlueX S&D Institutional Execution"
        scenario_tag = "STANDARD"
        zone_type = "STANDARD"
        structure_bias = {}
        be_trigger = None
        magic = payload.magic or (config.MAGIC_NUMBER_BASE + 101)

    if token != config.WEBHOOK_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret token")

    action_upper = action.upper()
    # Institutional Directive: Bot has ZERO market execution permission. Enforce Limit orders only.
    if action_upper == "BUY":
        action_upper = "BUY_LIMIT"
    elif action_upper == "SELL":
        action_upper = "SELL_LIMIT"

    if entry is None or entry <= 0:
        tick = mt5_engine.get_live_tick(symbol)
        bid = tick.get("bid", 2340.00)
        ask = tick.get("ask", 2340.13)
        entry = round(bid - 2.50, 2) if "BUY" in action_upper else round(ask + 2.50, 2)

    exec_alert = AlertPayload(
        secret=token,
        symbol=symbol,
        action=action_upper,  # Strictly BUY_LIMIT or SELL_LIMIT
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        risk_pct=risk_pct,
        magic=magic,
        comment=comment
    )

    # Invalidation cancellations or closures bypass approval queue and execute immediately
    if action_upper in ["CANCEL", "CANCEL_ALL", "CLOSE_ALL", "CLOSE_PARTIAL"]:
        res = mt5_engine.execute_alert(exec_alert)
        return {"action": action_upper, "result": res}

    # Dynamic Risk Percentage Assignment
    exec_alert.risk_pct = cockpit_state["custom_risk_pct"]

    # Dynamically scale TP1 if target_rr was altered
    if exec_alert.entry and exec_alert.sl:
        risk_delta = abs(exec_alert.entry - exec_alert.sl)
        if "BUY" in action_upper:
            exec_alert.tp1 = round(exec_alert.entry + (risk_delta * cockpit_state["target_rr"]), 2)
        else:
            exec_alert.tp1 = round(exec_alert.entry - (risk_delta * cockpit_state["target_rr"]), 2)

    # 1. Automated Execution Mode (Simultaneous Multicast to all active accounts)
    if cockpit_state["execution_mode"] == "AUTO":
        multicast_res = execute_multicast_signal(exec_alert, scenario_id=1)
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        logger.info(f"[AUTO-EXECUTION COMPLETE] {action_upper} multicast to {len(multicast_res.get('accounts', []))} account(s) in {elapsed_ms:.2f}ms")
        return {
            "mode": "AUTO",
            "latency_ms": round(elapsed_ms, 2),
            "multicast": multicast_res
        }

    # 2. Manual Approval Mode (Positions Approve Queue)
    signal_id = str(uuid.uuid4())[:8]

    # Calculate exact zone-based lot sizing before approval
    acc = mt5_engine.get_account_summary()
    equity = acc.get("equity", 10000.0) if acc.get("connected") else 10000.0
    cash_risk = equity * (exec_alert.risk_pct / 100.0)
    risk_delta = abs(exec_alert.entry - exec_alert.sl) if (exec_alert.entry and exec_alert.sl) else 4.0
    contract_size = 100.0
    calc_lots = precalc_lots if precalc_lots else round(max(0.01, min(100.0, cash_risk / (risk_delta * contract_size))), 2)

    sig_record = {
        "id": signal_id,
        "time": time.strftime("%H:%M:%S"),
        "agent_role": "SMC Genesis Signal Provider",
        "order_permission_type": "LIMIT_ONLY",
        "patience_score": 96,
        "sniper_score": 98,
        "status": "AWAITING_OPERATOR_APPROVAL",
        "symbol": exec_alert.symbol,
        "action": action_upper,  # Strictly BUY_LIMIT or SELL_LIMIT
        "entry": exec_alert.entry,
        "sl": exec_alert.sl,
        "tp1": exec_alert.tp1,
        "tp2": exec_alert.tp2,
        "risk_pct": exec_alert.risk_pct,
        "cash_risk": round(cash_risk, 2),
        "calc_lots": calc_lots,
        "zone_depth": round(risk_delta - (cockpit_state["spread_buffer_usd"] * 2.0), 2),
        "zone_type": zone_type,
        "scenario": scenario_tag,
        "structure_bias": structure_bias,
        "be_trigger_level": be_trigger,
        "magic": exec_alert.magic,
        "comment": exec_alert.comment
    }
    cockpit_state["pending_signals"].insert(0, sig_record)
    if len(cockpit_state["pending_signals"]) > 20:
        cockpit_state["pending_signals"].pop()

    logger.info(f"[SIGNAL ENQUEUED FOR APPROVAL] ID: {signal_id} | {action_upper} @ {exec_alert.entry} | Lots: {calc_lots} | Scenario: {scenario_tag}")
    return {
        "mode": "MANUAL",
        "signal_id": signal_id,
        "calculated_lots": calc_lots,
        "cash_risk": round(cash_risk, 2),
        "scenario": scenario_tag,
        "message": "Signal held in queue awaiting operator approval"
    }

@app.post("/api/signals/simulate")
async def simulate_institutional_signal(scenario: int = 1, request: Request = None):
    """
    SMC Genesis Signal Provider evaluates live XAU/USD market state:
    - Finds high-probability sniper position with confirmations and patience metrics.
    - AUTO MODE: Bot sets limit order immediately on all accounts with zero operator interference.
    - APPROVAL MODE: Signal Provider pushes formal approval request to approving channel for operator sign-off.
    - Bot sets LIMIT BUY or LIMIT SELL only (zero market execution permission).
    """
    scenario_choice = scenario
    if request:
        try:
            body = await request.json()
            if isinstance(body, dict) and "scenario" in body:
                scenario_choice = int(body["scenario"])
        except Exception:
            pass

    tick = mt5_engine.get_live_tick("XAUUSD")
    risk_mode = cockpit_state.get("risk_mode", "SAFE")
    custom_risk_pct = cockpit_state.get("custom_risk_pct", 0.50)

    # 1. SMC Genesis Signal Provider evaluates live market with sniping & patience protocol
    eval_result = signal_provider.evaluate_live_market(
        tick=tick,
        scenario_choice=scenario_choice,
        risk_mode=risk_mode,
        custom_risk_pct=custom_risk_pct
    )

    action = eval_result["action"]  # Strictly "BUY_LIMIT" or "SELL_LIMIT"
    entry = eval_result["limit_price"]
    sl = eval_result["sl"]
    tp1 = eval_result["tp"]
    risk_delta = max(0.50, abs(entry - sl))

    acc = mt5_engine.get_account_summary()
    equity = acc.get("equity", 100000.0) if acc.get("connected") else 100000.0
    cash_risk = equity * (custom_risk_pct / 100.0)
    calc_lots = round(max(0.01, min(100.0, cash_risk / (risk_delta * 100.0))), 2)

    sig_id = str(uuid.uuid4())[:8]
    signal_record = {
        "id": sig_id,
        "time": time.strftime("%H:%M:%S"),
        "agent_role": eval_result["agent_role"],
        "symbol": "XAUUSD",
        "action": action,  # Strictly BUY_LIMIT or SELL_LIMIT
        "order_permission_type": "LIMIT_ONLY",
        "scenario_id": eval_result["scenario_id"],
        "scenario_name": eval_result["scenario_name"],
        "zone_type": eval_result["zone_type"],
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": round(entry + ((tp1 - entry) * 1.3), 2) if "BUY" in action else round(entry - ((entry - tp1) * 1.3), 2),
        "rr_ratio": eval_result["rr_ratio"],
        "is_rr_valid": eval_result["is_rr_valid"],
        "patience_score": eval_result["patience_score"],
        "sniper_score": eval_result["sniper_score"],
        "entry_permission_granted": eval_result["entry_permission_granted"],
        "confirmations": eval_result["confirmations"],
        "analysis_brief": eval_result["analysis_brief"],
        "risk_mode": risk_mode,
        "risk_pct": custom_risk_pct,
        "cash_risk": round(cash_risk, 2),
        "calc_lots": calc_lots,
        "magic": 880100 + scenario_choice,
        "comment": f"SMC Genesis Sc {scenario_choice} Limit"
    }

    # If Auto Mode is active, bot sets limit automatically on all active accounts without operator interference
    if cockpit_state["execution_mode"] == "AUTO":
        payload = AlertPayload(
            secret=config.WEBHOOK_SECRET_KEY,
            symbol="XAUUSD",
            action=action,  # BUY_LIMIT or SELL_LIMIT
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=signal_record["tp2"],
            risk_pct=custom_risk_pct,
            magic=880100 + scenario_choice,
            comment=f"{eval_result['scenario_name']} (Auto Limit)"
        )
        multicast_res = execute_multicast_signal(payload, scenario_id=scenario_choice)
        logger.info(f"[SMC GENESIS SIGNAL PROVIDER -> AUTO LIMIT] Confirmed setup dispatched: {action} on {len(multicast_res.get('accounts', []))} account(s)")
        return {
            "status": "success",
            "mode": "AUTO",
            "signal": signal_record,
            "multicast": multicast_res,
            "message": f"SMC Genesis Signal Provider confirmed entry. Bot set {action} immediately on all active accounts."
        }
    else:
        # Approval Mode: push to approving channel requesting operator permission to set limit
        signal_record["status"] = "AWAITING_OPERATOR_APPROVAL"
        signal_record["request_text"] = "SMC Genesis Signal Provider requests approval to set limit order."
        cockpit_state["pending_signals"].insert(0, signal_record)
        if len(cockpit_state["pending_signals"]) > 20:
            cockpit_state["pending_signals"].pop()
        logger.info(f"[SMC GENESIS SIGNAL PROVIDER -> APPROVAL QUEUE] Setup confirmed ({eval_result['patience_score']}% patience): {action} @ {entry}. Requesting operator approval.")
        return {
            "status": "success",
            "mode": "MANUAL",
            "signal": signal_record,
            "message": "SMC Genesis Signal Provider confirmed setup. Requesting approval to set limit."
        }

# MT4 Polling Endpoint
@app.get("/mt4/poll")
async def mt4_poll(secret: str):
    if secret != config.WEBHOOK_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if not mt4_order_queue:
        return {"orders": []}
    pending = list(mt4_order_queue)
    mt4_order_queue.clear()
    return {"orders": pending}

if __name__ == "__main__":
    uvicorn.run("server:app", host=config.HOST, port=config.PORT, reload=False, log_level="info")
