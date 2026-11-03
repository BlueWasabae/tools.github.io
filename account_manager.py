# ==============================================================================
# BLUEX QUANTITATIVE EXECUTION BRIDGE - MULTI-ACCOUNT MT5 MANAGER
# Allows operators to configure, persist, and hot-switch multiple MT5 accounts
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
    is_active: bool = False

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
                "is_active": True
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
            target_acc = existing
        else:
            new_acc = {
                "id": acc_id,
                "name": data.get("name", f"Account #{data['login']}"),
                "login": int(data["login"]),
                "password": data.get("password", ""),
                "server": data.get("server", "MetaQuotes-Demo"),
                "path": data.get("path", r"C:\Program Files\MetaTrader 5\terminal64.exe"),
                "is_active": len(self.accounts) == 0
            }
            self.accounts.append(new_acc)
            target_acc = new_acc

        self.save_accounts()
        return target_acc

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
