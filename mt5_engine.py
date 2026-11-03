# ==============================================================================
# BLUEX QUANTITATIVE EXECUTION BRIDGE - METATRADER 5 NATIVE ENGINE
# High-speed Windows IPC execution engine via official MetaTrader 5 API
# Strict Non-Repainting Institutional Execution Protocol
# ==============================================================================

import os
import sys
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Tuple, Optional, List

# Ensure directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from config import SystemConfig, AlertPayload

logger = logging.getLogger("BlueX.MT5Engine")

class MT5ExecutionEngine:
    def __init__(self, config: SystemConfig):
        self.config = config
        self.initialized = False

    def initialize(self) -> bool:
        """Establishes high-performance IPC connection to MetaTrader 5 terminal."""
        init_kwargs: Dict[str, Any] = {"path": self.config.MT5_PATH}
        if self.config.MT5_LOGIN > 0 and self.config.MT5_PASSWORD and self.config.MT5_SERVER:
            init_kwargs["login"] = self.config.MT5_LOGIN
            init_kwargs["password"] = self.config.MT5_PASSWORD
            init_kwargs["server"] = self.config.MT5_SERVER

        if not mt5.initialize(**init_kwargs):
            logger.error(f"[MT5] Initialization failed: {mt5.last_error()}")
            return False

        account_info = mt5.account_info()
        if account_info is None:
            logger.error("[MT5] Failed to fetch account information.")
            return False

        self.initialized = True
        logger.info(
            f"[MT5] Connected successfully. Account: {account_info.login} | "
            f"Broker: {account_info.company} | Currency: {account_info.currency} | "
            f"Balance: {account_info.balance:.2f} | Equity: {account_info.equity:.2f}"
        )
        return True

    def shutdown(self):
        """Terminates IPC connection to MetaTrader 5."""
        if self.initialized:
            mt5.shutdown()
            self.initialized = False
            logger.info("[MT5] Terminal connection terminated.")

    def switch_account(self, account_dict: Dict[str, Any]) -> bool:
        """Hot-switches MT5 connection to a specified account."""
        self.shutdown()
        init_kwargs = {
            "path": account_dict.get("path") or self.config.MT5_PATH,
            "login": int(account_dict["login"]),
            "server": account_dict.get("server") or ""
        }
        if account_dict.get("password"):
            init_kwargs["password"] = account_dict["password"]

        if not mt5.initialize(**init_kwargs):
            logger.error(f"[MT5] Hot-switch to #{account_dict['login']} failed: {mt5.last_error()}")
            # Fallback re-init
            self.initialize()
            return False

        self.initialized = True
        logger.info(f"[MT5] Hot-switched to account #{account_dict['login']} on {account_dict.get('server')}")
        return True

    def resolve_symbol(self, requested_symbol: str) -> Optional[str]:
        """Resolves broker-specific symbol naming conventions (e.g. XAUUSD, GOLD, XAUUSDm)."""
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            return None

        candidates = [
            requested_symbol.upper(),
            "XAUUSD",
            "GOLD",
            f"{requested_symbol.upper()}m",
            f"{requested_symbol.upper()}.a",
            f"{requested_symbol.upper()}+",
            f"{requested_symbol.upper()}pro"
        ]

        for s in all_symbols:
            if s.name in candidates or requested_symbol.upper() in s.name:
                mt5.symbol_select(s.name, True)
                return s.name

        return None

    def get_account_summary(self) -> Dict[str, Any]:
        """Fetches live account telemetry."""
        if not self.initialized and not self.initialize():
            return {"connected": False}

        acc = mt5.account_info()
        if not acc:
            return {"connected": False}

        return {
            "connected": True,
            "login": acc.login,
            "broker": acc.company,
            "currency": acc.currency,
            "balance": round(acc.balance, 2),
            "equity": round(acc.equity, 2),
            "margin": round(acc.margin, 2),
            "margin_free": round(acc.margin_free, 2),
            "margin_level": round(acc.margin_level, 2) if acc.margin > 0 else 0.0,
            "profit": round(acc.profit, 2),
            "leverage": acc.leverage
        }

    def get_live_tick(self, symbol: str) -> Dict[str, Any]:
        """Fetches live bid/ask/spread for symbol."""
        sym = self.resolve_symbol(symbol)
        if not sym:
            return {"error": "Symbol not found"}

        tick = mt5.symbol_info_tick(sym)
        sym_info = mt5.symbol_info(sym)
        if not tick or not sym_info:
            return {"error": "Unable to pull live tick"}

        point = sym_info.point if sym_info.point > 0 else 0.01
        spread_points = round((tick.ask - tick.bid) / point, 1)

        return {
            "symbol": sym,
            "bid": round(tick.bid, 2),
            "ask": round(tick.ask, 2),
            "spread_points": spread_points,
            "spread_usd": round(tick.ask - tick.bid, 2),
            "time": tick.time
        }

    def get_open_positions(self, symbol: str = "XAUUSD") -> List[Dict[str, Any]]:
        """Queries live open market positions."""
        if not self.initialized and not self.initialize():
            return []

        sym = self.resolve_symbol(symbol)
        positions = mt5.positions_get(symbol=sym) if sym else mt5.positions_get()
        if positions is None:
            return []

        res = []
        for p in positions:
            res.append({
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                "volume": round(p.volume, 2),
                "price_open": round(p.price_open, 2),
                "sl": round(p.sl, 2),
                "tp": round(p.tp, 2),
                "price_current": round(p.price_current, 2),
                "profit": round(p.profit, 2),
                "magic": p.magic,
                "comment": p.comment,
                "time": p.time
            })
        return res

    def get_pending_orders(self, symbol: str = "XAUUSD") -> List[Dict[str, Any]]:
        """Queries active pending orders (BUY_LIMIT, SELL_LIMIT, etc.)."""
        if not self.initialized and not self.initialize():
            return []

        sym = self.resolve_symbol(symbol)
        orders = mt5.orders_get(symbol=sym) if sym else mt5.orders_get()
        if orders is None:
            return []

        type_map = {
            mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
            mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
            mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
            mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP"
        }

        res = []
        for o in orders:
            res.append({
                "ticket": o.ticket,
                "symbol": o.symbol,
                "type": type_map.get(o.type, f"TYPE_{o.type}"),
                "volume": round(o.volume_current, 2),
                "price_open": round(o.price_open, 2),
                "sl": round(o.sl, 2),
                "tp": round(o.tp, 2),
                "magic": o.magic,
                "comment": o.comment,
                "time_setup": o.time_setup
            })
        return res

    def calculate_lot_size(
        self,
        symbol: str,
        entry_price: float,
        sl_price: float,
        risk_pct: float
    ) -> Tuple[float, float]:
        """Calculates exact fractional risk lot size for institutional execution."""
        account_info = mt5.account_info()
        symbol_info = mt5.symbol_info(symbol)

        if account_info is None or symbol_info is None:
            raise ValueError(f"Unable to query market parameters for {symbol}")

        equity = account_info.equity
        cash_risk = equity * (min(risk_pct, self.config.MAX_RISK_PCT) / 100.0)
        price_delta = abs(entry_price - sl_price)

        if price_delta <= 0:
            raise ValueError("Entry price and Stop Loss cannot be identical.")

        tick_size = symbol_info.trade_tick_size if symbol_info.trade_tick_size > 0 else 0.01
        tick_value = symbol_info.trade_tick_value if symbol_info.trade_tick_value > 0 else 1.0
        contract_size = symbol_info.trade_contract_size if symbol_info.trade_contract_size > 0 else 100.0

        points_at_risk = price_delta / tick_size
        cost_per_lot_risk = points_at_risk * tick_value

        if cost_per_lot_risk <= 0:
            raw_lots = (cash_risk / (price_delta * contract_size))
        else:
            raw_lots = cash_risk / cost_per_lot_risk

        lot_step = symbol_info.volume_step if symbol_info.volume_step > 0 else 0.01
        min_lot = symbol_info.volume_min if symbol_info.volume_min > 0 else 0.01
        max_lot = symbol_info.volume_max if symbol_info.volume_max > 0 else 100.0

        steps = math.floor(raw_lots / lot_step)
        calculated_lot = steps * lot_step
        final_lot = max(min_lot, min(max_lot, calculated_lot))
        final_lot = round(final_lot, 2)

        return final_lot, cash_risk

    def execute_alert(self, payload: AlertPayload) -> Dict[str, Any]:
        """Dispatches mechanical institutional order to MetaTrader 5."""
        if not self.initialized and not self.initialize():
            return {"status": "error", "message": "MT5 terminal offline"}

        symbol = self.resolve_symbol(payload.symbol)
        if not symbol:
            return {"status": "error", "message": f"Symbol {payload.symbol} could not be resolved on broker"}

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"status": "error", "message": f"Cannot acquire live tick for {symbol}"}

        symbol_info = mt5.symbol_info(symbol)
        spread_points = (tick.ask - tick.bid) / symbol_info.point
        if spread_points > self.config.MAX_SPREAD_POINTS:
            return {
                "status": "rejected",
                "message": f"Spread {spread_points:.1f} points exceeds institutional threshold of {self.config.MAX_SPREAD_POINTS}"
            }

        action_upper = payload.action.upper()

        if action_upper in ["CANCEL", "CANCEL_ALL"]:
            return self._cancel_pending_orders(symbol, payload.magic)

        if action_upper in ["CLOSE_ALL", "CLOSE_PARTIAL"]:
            return self._close_positions(symbol, payload.magic, partial=(action_upper == "CLOSE_PARTIAL"))

        entry = payload.entry if payload.entry is not None else (tick.ask if "BUY" in action_upper else tick.bid)
        sl = payload.sl
        tp = payload.tp1

        lot_size, cash_risk = self.calculate_lot_size(
            symbol=symbol,
            entry_price=entry,
            sl_price=sl,
            risk_pct=payload.risk_pct or self.config.DEFAULT_RISK_PCT
        )

        request: Dict[str, Any] = {
            "symbol": symbol,
            "volume": lot_size,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": self.config.MAX_SLIPPAGE_POINTS,
            "magic": payload.magic or self.config.MAGIC_NUMBER_BASE,
            "comment": payload.comment[:31] if payload.comment else "BlueX S&D Execution",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC
        }

        if action_upper == "BUY":
            request["action"] = mt5.TRADE_ACTION_DEAL
            request["type"] = mt5.ORDER_TYPE_BUY
            request["price"] = tick.ask
        elif action_upper == "SELL":
            request["action"] = mt5.TRADE_ACTION_DEAL
            request["type"] = mt5.ORDER_TYPE_SELL
            request["price"] = tick.bid
        elif action_upper == "BUY_LIMIT":
            request["action"] = mt5.TRADE_ACTION_PENDING
            request["type"] = mt5.ORDER_TYPE_BUY_LIMIT
            request["price"] = float(entry)
            request["type_filling"] = mt5.ORDER_FILLING_RETURN
        elif action_upper == "SELL_LIMIT":
            request["action"] = mt5.TRADE_ACTION_PENDING
            request["type"] = mt5.ORDER_TYPE_SELL_LIMIT
            request["price"] = float(entry)
            request["type_filling"] = mt5.ORDER_FILLING_RETURN
        else:
            return {"status": "error", "message": f"Unsupported action type: {action_upper}"}

        result = mt5.order_send(request)
        if result is None:
            return {"status": "error", "message": f"Execution failed: {mt5.last_error()}"}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "status": "failed",
                "retcode": result.retcode,
                "comment": result.comment,
                "message": f"Broker returned code {result.retcode}: {result.comment}"
            }

        return {
            "status": "success",
            "order_ticket": result.order,
            "deal_ticket": result.deal,
            "symbol": symbol,
            "action": action_upper,
            "volume": lot_size,
            "entry_price": entry,
            "sl": sl,
            "tp": tp,
            "risk_cash": round(cash_risk, 2)
        }

    def move_all_to_breakeven(self, symbol: str = "XAUUSD", buffer_usd: float = 0.40) -> Dict[str, Any]:
        """
        Modifies all open positions to Breakeven (+ spread buffer).
        For BUY: new SL = entry + buffer_usd (if current price > new SL).
        For SELL: new SL = entry - buffer_usd (if current price < new SL).
        """
        if not self.initialized and not self.initialize():
            return {"status": "error", "message": "MT5 offline"}

        sym = self.resolve_symbol(symbol)
        positions = mt5.positions_get(symbol=sym) if sym else mt5.positions_get()
        if not positions:
            return {"status": "success", "modified_count": 0, "message": "No open positions to adjust"}

        modified = 0
        failed = 0

        for p in positions:
            new_sl = round(p.price_open + buffer_usd if p.type == mt5.POSITION_TYPE_BUY else p.price_open - buffer_usd, 2)

            # Safeguard: only move to BE if current price is in profit past new_sl
            is_profitable = (p.type == mt5.POSITION_TYPE_BUY and p.price_current > new_sl) or \
                            (p.type == mt5.POSITION_TYPE_SELL and p.price_current < new_sl)

            if not is_profitable:
                logger.info(f"Position #{p.ticket} not sufficiently in profit for BE lock.")
                continue

            # Check if already at or better than BE
            if p.type == mt5.POSITION_TYPE_BUY and p.sl >= new_sl:
                continue
            if p.type == mt5.POSITION_TYPE_SELL and p.sl > 0 and p.sl <= new_sl:
                continue

            req = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": p.ticket,
                "symbol": p.symbol,
                "sl": new_sl,
                "tp": p.tp
            }
            res = mt5.order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                modified += 1
            else:
                failed += 1

        return {
            "status": "success",
            "modified_count": modified,
            "skipped_or_failed": failed,
            "message": f"Moved {modified} position(s) to Breakeven (+${buffer_usd:.2f})"
        }

    def close_all_positions_and_pending(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        """Emergency Kill Switch: Closes 100% of open positions and deletes all pending limit/stop orders."""
        if not self.initialized and not self.initialize():
            return {"status": "error", "message": "MT5 offline"}

        sym = self.resolve_symbol(symbol)
        closed_positions = 0
        canceled_orders = 0

        # 1. Close Open Market Positions
        positions = mt5.positions_get(symbol=sym) if sym else mt5.positions_get()
        if positions:
            for p in positions:
                tick = mt5.symbol_info_tick(p.symbol)
                price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
                order_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY

                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": p.ticket,
                    "symbol": p.symbol,
                    "volume": p.volume,
                    "type": order_type,
                    "price": price,
                    "deviation": self.config.MAX_SLIPPAGE_POINTS,
                    "comment": "BlueX Emergency Close All"
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    closed_positions += 1

        # 2. Cancel All Pending Orders
        orders = mt5.orders_get(symbol=sym) if sym else mt5.orders_get()
        if orders:
            for o in orders:
                req = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": o.ticket
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    canceled_orders += 1

        return {
            "status": "success",
            "closed_positions": closed_positions,
            "canceled_orders": canceled_orders,
            "message": f"Closed {closed_positions} open position(s) and canceled {canceled_orders} pending order(s)."
        }

    def close_single_ticket(self, ticket: int) -> Dict[str, Any]:
        """Closes a single position ticket."""
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"status": "error", "message": f"Position #{ticket} not found"}

        p = positions[0]
        tick = mt5.symbol_info_tick(p.symbol)
        price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
        order_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": p.ticket,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": order_type,
            "price": price,
            "deviation": self.config.MAX_SLIPPAGE_POINTS,
            "comment": "BlueX Manual Close"
        }
        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            return {"status": "success", "message": f"Position #{ticket} closed successfully"}
        return {"status": "failed", "message": f"Broker error: {res.comment if res else mt5.last_error()}"}

    def _cancel_pending_orders(self, symbol: str, magic: Optional[int]) -> Dict[str, Any]:
        orders = mt5.orders_get(symbol=symbol)
        if not orders:
            return {"status": "success", "canceled_count": 0, "message": "No active pending orders to cancel"}

        canceled = 0
        for ord in orders:
            if magic and ord.magic != magic:
                continue
            req = {"action": mt5.TRADE_ACTION_REMOVE, "order": ord.ticket}
            res = mt5.order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                canceled += 1

        return {"status": "success", "canceled_count": canceled}

    def _close_positions(self, symbol: str, magic: Optional[int], partial: bool = False) -> Dict[str, Any]:
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return {"status": "success", "closed_count": 0, "message": "No open positions found"}

        closed = 0
        for pos in positions:
            if magic and pos.magic != magic:
                continue

            symbol_info = mt5.symbol_info(symbol)
            close_vol = pos.volume
            if partial:
                close_vol = round(max(symbol_info.volume_min, pos.volume * 0.5), 2)

            tick = mt5.symbol_info_tick(symbol)
            order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask

            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": close_vol,
                "type": order_type,
                "position": pos.ticket,
                "price": price,
                "deviation": self.config.MAX_SLIPPAGE_POINTS,
                "magic": pos.magic,
                "comment": "BlueX Partial TP" if partial else "BlueX Invalidation Close"
            }
            res = mt5.order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                closed += 1

        return {"status": "success", "closed_count": closed}

    def modify_position_sltp(self, ticket: int, sl: float, tp: float) -> Dict[str, Any]:
        """Modifies Stop Loss and Take Profit of a specific live position."""
        if not self.initialized and not self.initialize():
            return {"status": "error", "message": "MT5 offline"}

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"status": "error", "message": f"Position #{ticket} not found"}

        p = positions[0]
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": p.ticket,
            "symbol": p.symbol,
            "sl": round(float(sl), 2) if sl > 0 else 0.0,
            "tp": round(float(tp), 2) if tp > 0 else 0.0
        }
        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[MT5] Position #{ticket} SL/TP modified -> SL: {sl:.2f}, TP: {tp:.2f}")
            return {"status": "success", "message": f"Position #{ticket} SL/TP modified to SL:{sl:.2f} TP:{tp:.2f}"}
        return {"status": "failed", "message": f"Broker error: {res.comment if res else mt5.last_error()}"}

    def close_partial_position(self, ticket: int, volume: float) -> Dict[str, Any]:
        """Closes a specific lot volume from an active position."""
        if not self.initialized and not self.initialize():
            return {"status": "error", "message": "MT5 offline"}

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"status": "error", "message": f"Position #{ticket} not found"}

        p = positions[0]
        vol = round(float(volume), 2)
        if vol <= 0 or vol > p.volume:
            vol = p.volume

        tick = mt5.symbol_info_tick(p.symbol)
        price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
        order_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": p.ticket,
            "symbol": p.symbol,
            "volume": vol,
            "type": order_type,
            "price": price,
            "deviation": self.config.MAX_SLIPPAGE_POINTS,
            "comment": f"BlueX Partial Close {vol} Lots"
        }
        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[MT5] Position #{ticket} partial closed {vol} lots successfully.")
            return {"status": "success", "message": f"Closed {vol} lots of #{ticket}."}
        return {"status": "failed", "message": f"Broker error: {res.comment if res else mt5.last_error()}"}

    def get_deals_history(self, days: int = 90) -> Dict[str, Any]:
        """
        Retrieves real closed trade records and net performance statistics directly from MetaTrader 5 history.
        Zero mock data.
        """
        if not self.initialized and not self.initialize():
            return {
                "total_realized_pnl": 0.0,
                "total_volume_lots": 0.0,
                "closed_trades_count": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "deals": []
            }

        now = datetime.now()
        start = now - timedelta(days=days)
        history = mt5.history_deals_get(start, now)
        if history is None:
            return {
                "total_realized_pnl": 0.0,
                "total_volume_lots": 0.0,
                "closed_trades_count": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "deals": []
            }

        deals_list = []
        total_pnl = 0.0
        total_volume = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        wins = 0
        losses = 0

        for d in history:
            if d.entry in [mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT] or (d.profit != 0 and d.entry != mt5.DEAL_ENTRY_IN):
                deal_time = datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M:%S")
                net_deal_pnl = round(d.profit + d.swap + d.commission + d.fee, 2)
                total_pnl += net_deal_pnl
                total_volume += d.volume

                if net_deal_pnl > 0:
                    wins += 1
                    gross_profit += net_deal_pnl
                elif net_deal_pnl < 0:
                    losses += 1
                    gross_loss += abs(net_deal_pnl)

                deals_list.append({
                    "ticket": d.ticket,
                    "order": d.order,
                    "time": deal_time,
                    "symbol": d.symbol,
                    "type": "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
                    "volume": round(d.volume, 2),
                    "price": round(d.price, 2),
                    "profit": round(d.profit, 2),
                    "commission": round(d.commission, 2),
                    "swap": round(d.swap, 2),
                    "net_pnl": net_deal_pnl,
                    "comment": d.comment
                })

        closed_count = len(deals_list)
        win_rate = round((wins / closed_count * 100), 1) if closed_count > 0 else 0.0
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 0.0)

        deals_list.reverse()

        return {
            "total_realized_pnl": round(total_pnl, 2),
            "total_volume_lots": round(total_volume, 2),
            "closed_trades_count": closed_count,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "deals": deals_list
        }

    def check_and_apply_auto_be_2rr(self, symbol: str = "XAUUSD", buffer_usd: float = 0.40) -> List[Dict[str, Any]]:
        """
        Scans all open positions for XAUUSD.
        When price extends >= +2.0 RR from entry towards TP, automatically moves SL to Breakeven (+ spread buffer).
        """
        if not self.initialized and not self.initialize():
            return []

        sym = self.resolve_symbol(symbol)
        positions = mt5.positions_get(symbol=sym) if sym else mt5.positions_get()
        if not positions:
            return []

        actions_taken = []
        for p in positions:
            if p.type == mt5.POSITION_TYPE_BUY:
                if p.sl > 0 and p.price_open > p.sl:
                    risk_points = p.price_open - p.sl
                    target_2rr = p.price_open + (2.0 * risk_points)
                    new_sl = round(p.price_open + buffer_usd, 2)

                    if p.price_current >= target_2rr and p.sl < new_sl:
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": p.ticket,
                            "symbol": p.symbol,
                            "sl": new_sl,
                            "tp": p.tp
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            logger.info(f"[AUTO BE @ +2RR] Position #{p.ticket} reached +2RR ({p.price_current:.2f} >= {target_2rr:.2f}). SL moved to {new_sl:.2f}")
                            actions_taken.append({
                                "ticket": p.ticket,
                                "type": "BUY",
                                "open_price": p.price_open,
                                "current_price": p.price_current,
                                "new_sl": new_sl,
                                "trigger_2rr_level": target_2rr
                            })

            elif p.type == mt5.POSITION_TYPE_SELL:
                if p.sl > 0 and p.sl > p.price_open:
                    risk_points = p.sl - p.price_open
                    target_2rr = p.price_open - (2.0 * risk_points)
                    new_sl = round(p.price_open - buffer_usd, 2)

                    if p.price_current <= target_2rr and (p.sl > new_sl or p.sl == 0):
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": p.ticket,
                            "symbol": p.symbol,
                            "sl": new_sl,
                            "tp": p.tp
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            logger.info(f"[AUTO BE @ +2RR] Position #{p.ticket} reached +2RR ({p.price_current:.2f} <= {target_2rr:.2f}). SL moved to {new_sl:.2f}")
                            actions_taken.append({
                                "ticket": p.ticket,
                                "type": "SELL",
                                "open_price": p.price_open,
                                "current_price": p.price_current,
                                "new_sl": new_sl,
                                "trigger_2rr_level": target_2rr
                            })

        return actions_taken
