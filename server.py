# ==============================================================================
# BLUEX QUANTITATIVE EXECUTION BRIDGE & COCKPIT SERVER
# Microsecond TradingView -> MT5/MT4 Automation & Web Cockpit Middleware
# ==============================================================================

import os
import sys
import time
import uuid
import logging
from typing import Dict, Any, List, Optional

# Ensure directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from config import SystemConfig, AlertPayload
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

# MT5 Engine & Account Manager Instances
account_manager = AccountManager()
mt5_engine = MT5ExecutionEngine(config)

# Global Cockpit State
cockpit_state = {
    "risk_mode": "SAFE",            # "SAFE", "AGGRESSIVE", or "CUSTOM"
    "custom_risk_pct": 0.50,        # Granular risk percentage adjust (0.10% to 5.0%)
    "execution_mode": "MANUAL",      # "AUTO" (Direct execution) or "MANUAL" (Positions approve)
    "target_rr": 3.0,               # Target Risk:Reward ratio
    "spread_buffer_usd": 0.40,      # Dynamic spread buffer
    "auto_be_enabled": False,       # Auto BE after holding >= +2.0 RR
    "auto_be_trigger_rr": 2.0,      # Trigger multiple (+2.0 RR)
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
    auto_be_enabled: Optional[bool] = None
    auto_be_trigger_rr: Optional[float] = None

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

@app.get("/journal")
async def serve_journal():
    """Serves the institutional trading journal calendar."""
    journal_path = os.path.join(STATIC_DIR, "journal.html")
    if os.path.exists(journal_path):
        return FileResponse(journal_path)
    return {"message": "Trading Journal calendar initialized."}

# ==============================================================================
# COCKPIT STATE & SETTINGS ENDPOINTS
# ==============================================================================

@app.get("/api/state")
async def get_state():
    """Returns combined account, market, controls, and pending signals telemetry."""
    # Check and trigger auto-BE if enabled
    auto_be_actions = []
    if cockpit_state["auto_be_enabled"]:
        auto_be_actions = mt5_engine.check_and_apply_auto_be_2rr("XAUUSD", buffer_usd=cockpit_state["spread_buffer_usd"])

    acc = mt5_engine.get_account_summary()
    tick = mt5_engine.get_live_tick("XAUUSD")
    positions = mt5_engine.get_open_positions("XAUUSD")
    pending_orders = mt5_engine.get_pending_orders("XAUUSD")
    deals_summary = mt5_engine.get_deals_history(days=90)

    return {
        "risk_mode": cockpit_state["risk_mode"],
        "custom_risk_pct": cockpit_state["custom_risk_pct"],
        "execution_mode": cockpit_state["execution_mode"],
        "target_rr": cockpit_state["target_rr"],
        "spread_buffer_usd": cockpit_state["spread_buffer_usd"],
        "auto_be_enabled": cockpit_state["auto_be_enabled"],
        "auto_be_trigger_rr": cockpit_state["auto_be_trigger_rr"],
        "auto_be_actions_recent": auto_be_actions,
        "account": acc,
        "accounts_list": account_manager.get_accounts(),
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

    if settings.spread_buffer_usd is not None and 0.1 <= settings.spread_buffer_usd <= 5.0:
        cockpit_state["spread_buffer_usd"] = settings.spread_buffer_usd

    if settings.auto_be_enabled is not None:
        cockpit_state["auto_be_enabled"] = settings.auto_be_enabled

    if settings.auto_be_trigger_rr is not None and 1.0 <= settings.auto_be_trigger_rr <= 5.0:
        cockpit_state["auto_be_trigger_rr"] = settings.auto_be_trigger_rr

    logger.info(f"[SETTINGS UPDATED] Risk: {cockpit_state['custom_risk_pct']}% | Mode: {cockpit_state['risk_mode']} | Auto-BE: {cockpit_state['auto_be_enabled']} | RR: 1:{cockpit_state['target_rr']}")
    return {"status": "success", "settings": cockpit_state}

# ==============================================================================
# MULTI-ACCOUNT MT5 MANAGEMENT ENDPOINTS
# ==============================================================================

@app.get("/api/accounts")
async def list_accounts():
    return {
        "accounts": account_manager.get_accounts(),
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
# SIGNAL APPROVAL QUEUE (Positions Approve Pipeline)
# ==============================================================================

@app.post("/api/signals/{signal_id}/approve")
async def approve_signal(signal_id: str):
    """Executes a queued signal to MT5 after manual operator verification."""
    target_idx = None
    for i, s in enumerate(cockpit_state["pending_signals"]):
        if s["id"] == signal_id:
            target_idx = i
            break

    if target_idx is None:
        raise HTTPException(status_code=404, detail="Signal not found or already processed")

    sig = cockpit_state["pending_signals"].pop(target_idx)

    # Recalculate TP based on current dynamic RR setting
    entry = sig["entry"]
    sl = sig["sl"]
    risk_delta = abs(entry - sl)
    rr = cockpit_state["target_rr"]

    if "BUY" in sig["action"].upper():
        tp = round(entry + (risk_delta * rr), 2)
    else:
        tp = round(entry - (risk_delta * rr), 2)

    risk_pct = cockpit_state["custom_risk_pct"]

    payload = AlertPayload(
        secret=config.WEBHOOK_SECRET_KEY,
        symbol=sig["symbol"],
        action=sig["action"],
        entry=entry,
        sl=sl,
        tp1=tp,
        risk_pct=risk_pct,
        magic=sig.get("magic", 880101),
        comment=f"BlueX Approved ({risk_pct}%)"
    )

    mt5_res = mt5_engine.execute_alert(payload)
    logger.info(f"[MANUAL SIGNAL APPROVED] Dispatched ticket {signal_id} -> Result: {mt5_res.get('status')}")

    return {
        "status": "success",
        "message": f"Signal {signal_id} approved and dispatched to MT5",
        "mt5_response": mt5_res
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
async def handle_tradingview_webhook(payload: AlertPayload, request: Request):
    """
    Primary ingress for TradingView alerts and BlueX Market Scanner.
    - If execution_mode == "AUTO": Direct microsecond execution to MT5.
    - If execution_mode == "MANUAL": Pushes to Signal Approval Queue.
    """
    t_start = time.perf_counter()

    if payload.secret != config.WEBHOOK_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret token")

    action_upper = payload.action.upper()

    # Invalidation cancellations or closures bypass approval queue and execute immediately
    if action_upper in ["CANCEL", "CANCEL_ALL", "CLOSE_ALL", "CLOSE_PARTIAL"]:
        res = mt5_engine.execute_alert(payload)
        return {"action": action_upper, "result": res}

    # Dynamic Risk Percentage Assignment
    payload.risk_pct = cockpit_state["custom_risk_pct"]

    # Dynamically scale TP1 if target_rr was altered
    if payload.entry and payload.sl:
        risk_delta = abs(payload.entry - payload.sl)
        if "BUY" in action_upper:
            payload.tp1 = round(payload.entry + (risk_delta * cockpit_state["target_rr"]), 2)
        else:
            payload.tp1 = round(payload.entry - (risk_delta * cockpit_state["target_rr"]), 2)

    # 1. Automated Execution Mode
    if cockpit_state["execution_mode"] == "AUTO":
        mt5_result = mt5_engine.execute_alert(payload)
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        logger.info(f"[AUTO-EXECUTION COMPLETE] {action_upper} on {payload.symbol} in {elapsed_ms:.2f}ms")
        return {
            "mode": "AUTO",
            "latency_ms": round(elapsed_ms, 2),
            "mt5_response": mt5_result
        }

    # 2. Manual Approval Mode (Positions Approve Queue)
    signal_id = str(uuid.uuid4())[:8]

    # Calculate exact zone-based lot sizing before approval
    acc = mt5_engine.get_account_summary()
    equity = acc.get("equity", 10000.0) if acc.get("connected") else 10000.0
    cash_risk = equity * (payload.risk_pct / 100.0)
    risk_delta = abs(payload.entry - payload.sl) if (payload.entry and payload.sl) else 4.0
    contract_size = 100.0
    calc_lots = round(max(0.01, min(100.0, cash_risk / (risk_delta * contract_size))), 2)

    sig_record = {
        "id": signal_id,
        "time": time.strftime("%H:%M:%S"),
        "symbol": payload.symbol,
        "action": action_upper,
        "entry": payload.entry,
        "sl": payload.sl,
        "tp1": payload.tp1,
        "tp2": payload.tp2,
        "risk_pct": payload.risk_pct,
        "cash_risk": round(cash_risk, 2),
        "calc_lots": calc_lots,
        "zone_depth": round(risk_delta - (cockpit_state["spread_buffer_usd"] * 2.0), 2),
        "magic": payload.magic,
        "comment": payload.comment
    }
    cockpit_state["pending_signals"].insert(0, sig_record)
    if len(cockpit_state["pending_signals"]) > 20:
        cockpit_state["pending_signals"].pop()

    logger.info(f"[SIGNAL ENQUEUED FOR APPROVAL] ID: {signal_id} | {action_upper} @ {payload.entry} | Lots: {calc_lots}")
    return {
        "mode": "MANUAL",
        "signal_id": signal_id,
        "calculated_lots": calc_lots,
        "cash_risk": round(cash_risk, 2),
        "message": "Signal held in queue awaiting operator approval"
    }

@app.post("/api/signals/simulate")
async def simulate_institutional_signal():
    """Generates a test institutional zone setup on Gold for operator approval testing."""
    tick = mt5_engine.get_live_tick("XAUUSD")
    current_price = tick.get("bid", 3925.00) if not tick.get("error") else 3925.00
    spread_buf = cockpit_state["spread_buffer_usd"]

    # Generate synthetic DBR Demand Zone below price
    zone_top = round(current_price - 5.0, 2)
    zone_bottom = round(zone_top - 3.80, 2)
    entry = round(zone_top + spread_buf, 2)
    sl = round(zone_bottom - spread_buf, 2)
    risk_delta = entry - sl
    rr = cockpit_state["target_rr"]
    tp1 = round(entry + (risk_delta * rr), 2)
    tp2 = round(entry + (risk_delta * (rr + 2.0)), 2)

    risk_pct = cockpit_state["custom_risk_pct"]
    acc = mt5_engine.get_account_summary()
    equity = acc.get("equity", 10000.0) if acc.get("connected") else 10000.0
    cash_risk = equity * (risk_pct / 100.0)
    calc_lots = round(max(0.01, min(100.0, cash_risk / (risk_delta * 100.0))), 2)

    sig_id = str(uuid.uuid4())[:8]
    test_sig = {
        "id": sig_id,
        "time": time.strftime("%H:%M:%S"),
        "symbol": "XAUUSD",
        "action": "BUY_LIMIT",
        "zone_type": "DBR Demand",
        "zone_top": zone_top,
        "zone_bottom": zone_bottom,
        "zone_depth": round(zone_top - zone_bottom, 2),
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk_pct": risk_pct,
        "cash_risk": round(cash_risk, 2),
        "calc_lots": calc_lots,
        "magic": 880101,
        "comment": "Institutional DBR Demand Origin"
    }

    cockpit_state["pending_signals"].insert(0, test_sig)
    logger.info(f"[TEST SIGNAL SIMULATED] ID: {sig_id} | Entry: {entry} | Lots: {calc_lots} | Risk: ${cash_risk:.2f}")
    return {"status": "success", "signal": test_sig}

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
