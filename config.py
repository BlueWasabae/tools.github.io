# ==============================================================================
# BLUEX QUANTITATIVE EXECUTION BRIDGE - ENVIRONMENT CONFIGURATION
# Platform: MetaTrader 5 / MetaTrader 4 Windows Native Bridge
# Asset: Gold (XAU/USD)
# ==============================================================================

import os
from pydantic import BaseModel, Field
from typing import Optional

class SystemConfig:
    # Security
    WEBHOOK_SECRET_KEY: str = os.getenv("BLUEX_SECRET_KEY", "BLUEX_QUANT_SECURE_TOKEN_9981")
    PORT: int = int(os.getenv("BLUEX_PORT", "8000"))
    HOST: str = os.getenv("BLUEX_HOST", "0.0.0.0")

    # MetaTrader 5 Configuration
    MT5_PATH: str = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
    MT5_LOGIN: int = int(os.getenv("MT5_LOGIN", "0"))
    MT5_PASSWORD: str = os.getenv("MT5_PASSWORD", "")
    MT5_SERVER: str = os.getenv("MT5_SERVER", "")
    MT5_TIMEOUT_MS: int = 10000

    # MetaTrader 4 Configuration
    MT4_ENABLED: bool = os.getenv("MT4_ENABLED", "True").lower() == "true"
    MT4_HTTP_PORT: int = int(os.getenv("MT4_HTTP_PORT", "8001"))

    # Asset & Risk Parameters
    DEFAULT_SYMBOL: str = "XAUUSD"
    DEFAULT_RISK_PCT: float = 1.0        # Fractional account risk % (0.5% - 1.0%)
    MAX_RISK_PCT: float = 2.0            # Hard ceiling safeguard
    MIN_RR_RATIO: float = 3.0            # Enforced 1:3 minimum risk/reward ratio
    MAX_SLIPPAGE_POINTS: int = 30        # 3.0 pips on gold
    MAX_SPREAD_POINTS: int = 50          # 5.0 pips spread threshold filter

    # Execution Magic Numbers
    MAGIC_NUMBER_BASE: int = 880000

class AlertPayload(BaseModel):
    secret: str
    symbol: str = "XAUUSD"
    action: str  # BUY, SELL, BUY_LIMIT, SELL_LIMIT, CANCEL, CLOSE_PARTIAL, CLOSE_ALL
    entry: Optional[float] = None
    sl: float
    tp1: float
    tp2: Optional[float] = None
    risk_pct: Optional[float] = Field(default=1.0, ge=0.1, le=5.0)
    magic: Optional[int] = 880101
    comment: Optional[str] = "BlueX S&D Institutional Execution"
