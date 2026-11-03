# ==============================================================================
# BLUEX QUANTITATIVE EXECUTION BRIDGE - SYNTHETIC ALERT TEST HARNESS
# Simulates TradingView Webhook Alerts locally
# ==============================================================================

import requests
import json
import sys

URL = "http://127.0.0.1:8000/webhook"
SECRET = "BLUEX_QUANT_SECURE_TOKEN_9981"

test_payload = {
    "secret": SECRET,
    "symbol": "XAUUSD",
    "action": "BUY_LIMIT",
    "entry": 2730.50,
    "sl": 2724.00,
    "tp1": 2750.00,
    "tp2": 2770.00,
    "risk_pct": 1.0,
    "magic": 880101,
    "comment": "BlueX DBR Test Limit Execution"
}

print(f"[*] Dispatching test payload to {URL}...")
try:
    response = requests.post(URL, json=test_payload, timeout=5)
    print(f"[*] Response Status Code: {response.status_code}")
    print("[*] Response JSON:")
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"[!] Request failed: {e}")
