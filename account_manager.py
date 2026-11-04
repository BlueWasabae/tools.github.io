# ==============================================================================
# BLUEX QUANTITATIVE EXECUTION BRIDGE - MULTI-ACCOUNT MT5 MANAGER
# Allows operators to configure, persist, and hot-switch multiple MT5 accounts
# Supports simultaneous multicast execution and per-account tactical parameters
# ==============================================================================

import os
import sys
import time
import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("BlueX.AccountManager")

ACCOUNTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mt5_accounts.json")

class MT5AccountModel(BaseModel):
    id: str
    name: str                           # e.g. "FTMO Funded 100k", "Personal IC Markets", "Evaluation"
    login: int                          # Account Login number
    password: Optional[str] = ""        # Optional if stored in terminal
    server: str                         # Broker server name e.g. "MetaQuotes-Demo", "ICMarketsSC-Live"
    path: Optional[str] = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    is_active: bool = True
    auto_tp: bool = True                # Bot-decided Take Profit using S&D
    tp_cap_rr: Optional[float] = 3.0    # Optional TP Cap (Max RR ratio)
    tp_adjust_pts: float = 0.0          # Manual TP adjustment offset in points
    sl_cover_buffer: float = 0.40       # Dynamic spread and commission buffer in USD/points

class AccountManager:
    def __init__(self):
        self.accounts: List[Dict[str, Any]] = []
        self.load_accounts()

    def load_accounts(self):
        """Loads configured MT5 accounts from persistent storage."""
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    self.accounts = json.load(f)
                # Ensure all accounts have default per-account fields
                modified = False
                for acc in self.accounts:
                    if "auto_tp" not in acc:
                        acc["auto_tp"] = True
                        modified = True
                    if "tp_cap_rr" not in acc:
                        acc["tp_cap_rr"] = 3.0
                        modified = True
                    if "tp_adjust_pts" not in acc:
                        acc["tp_adjust_pts"] = 0.0
                        modified = True
                    if "sl_cover_buffer" not in acc:
                        acc["sl_cover_buffer"] = 0.40
                        modified = True
                if modified:
                    self.save_accounts()
                return
            except Exception as e:
                logger.error(f"Failed to parse accounts file: {e}")

        # Initialize with primary default account
        self.accounts = [
            {
                "id": "acc_default_1",
                "name": "Primary Trading Account",
                "login": 115076007,
                "password": "",
                "server": "MetaQuotes-Demo",
                "path": r"C:\Program Files\MetaTrader 5\terminal64.exe",
                "is_active": True,
                "auto_tp": True,
                "tp_cap_rr": 3.0,
                "tp_adjust_pts": 0.0,
                "sl_cover_buffer": 0.40
            }
        ]
        self.save_accounts()

    def save_accounts(self):
        """Persists MT5 accounts to disk."""
        try:
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.accounts, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save accounts file: {e}")

    def get_account_by_id(self, acc_id: str) -> Optional[Dict[str, Any]]:
        for acc in self.accounts:
            if acc["id"] == acc_id:
                return acc
        return None

    def get_accounts(self) -> List[Dict[str, Any]]:
        # Redact passwords for security
        sanitized = []
        for acc in self.accounts:
            a = dict(acc)
            a["has_password"] = bool(a.get("password"))
            a["password"] = "******" if a["has_password"] else ""
            sanitized.append(a)
        return sanitized

    def get_active_account(self) -> Optional[Dict[str, Any]]:
        for acc in self.accounts:
            if acc.get("is_active"):
                return acc
        if self.accounts:
            self.accounts[0]["is_active"] = True
            return self.accounts[0]
        return None

    def get_active_accounts(self) -> List[Dict[str, Any]]:
        """Returns all accounts enabled for simultaneous multi-account broadcast execution."""
        actives = [a for a in self.accounts if a.get("is_active")]
        if not actives and self.accounts:
            self.accounts[0]["is_active"] = True
            actives = [self.accounts[0]]
        return actives

    def add_or_update_account(self, data: Dict[str, Any]) -> Dict[str, Any]:
        acc_id = data.get("id") or f"acc_{int(time.time())}"
        existing = next((a for a in self.accounts if a["id"] == acc_id or a["login"] == data["login"]), None)

        if existing:
            existing["name"] = data.get("name", existing["name"])
            existing["login"] = int(data.get("login", existing["login"]))
            if data.get("password"):
                existing["password"] = data["password"]
            existing["server"] = data.get("server", existing["server"])
            existing["path"] = data.get("path", existing.get("path", r"C:\Program Files\MetaTrader 5\terminal64.exe"))
            if "is_active" in data:
                existing["is_active"] = bool(data["is_active"])
            if "auto_tp" in data:
                existing["auto_tp"] = bool(data["auto_tp"])
            if "tp_cap_rr" in data:
                existing["tp_cap_rr"] = float(data["tp_cap_rr"]) if data["tp_cap_rr"] is not None else None
            if "tp_adjust_pts" in data:
                existing["tp_adjust_pts"] = float(data["tp_adjust_pts"])
            if "sl_cover_buffer" in data:
                existing["sl_cover_buffer"] = float(data["sl_cover_buffer"])
            target_acc = existing
        else:
            new_acc = {
                "id": acc_id,
                "name": data.get("name", f"Account #{data['login']}"),
                "login": int(data["login"]),
                "password": data.get("password", ""),
                "server": data.get("server", "MetaQuotes-Demo"),
                "path": data.get("path", r"C:\Program Files\MetaTrader 5\terminal64.exe"),
                "is_active": True,
                "auto_tp": True,
                "tp_cap_rr": 3.0,
                "tp_adjust_pts": 0.0,
                "sl_cover_buffer": 0.40
            }
            self.accounts.append(new_acc)
            target_acc = new_acc

        self.save_accounts()
        return target_acc

    def update_account_settings(self, acc_id: str, settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        acc = self.get_account_by_id(acc_id)
        if not acc:
            return None
        if "name" in settings:
            acc["name"] = settings["name"]
        if "is_active" in settings:
            acc["is_active"] = bool(settings["is_active"])
        if "auto_tp" in settings:
            acc["auto_tp"] = bool(settings["auto_tp"])
        if "tp_cap_rr" in settings:
            acc["tp_cap_rr"] = float(settings["tp_cap_rr"]) if settings["tp_cap_rr"] is not None else None
        if "tp_adjust_pts" in settings:
            acc["tp_adjust_pts"] = float(settings["tp_adjust_pts"])
        if "sl_cover_buffer" in settings:
            acc["sl_cover_buffer"] = float(settings["sl_cover_buffer"])
        self.save_accounts()
        return acc

    def switch_active_account(self, acc_id: str) -> Optional[Dict[str, Any]]:
        target = None
        for acc in self.accounts:
            if acc["id"] == acc_id:
                acc["is_active"] = True
                target = acc
            else:
                acc["is_active"] = False

        if target:
            self.save_accounts()
        return target

    def delete_account(self, acc_id: str) -> bool:
        initial_len = len(self.accounts)
        self.accounts = [a for a in self.accounts if a["id"] != acc_id]
        if len(self.accounts) < initial_len:
            if not any(a.get("is_active") for a in self.accounts) and self.accounts:
                self.accounts[0]["is_active"] = True
            self.save_accounts()
            return True
        return False
