"""MANUAL test of MT5 order execution on a DEMO account. Run by the user, never by the app or an agent.

It places exactly one 0.01-lot test order the way the FVG executor does (app/fvg_execution.py): broker preflight
(order_check), ORDER_FILLING_RETURN for pending orders, SL/TP attached, a 2-hour specified expiry converted with
the SAME server time base as the feed (config/mt5_time.json), its own magic number and comment so the FVG engine
never mistakes it for a basket leg.

    .venv/Scripts/python.exe tools/mt5_test_order.py place            # 0.01 BUY LIMIT, 5.00 below the Ask (default)
    .venv/Scripts/python.exe tools/mt5_test_order.py place --market   # 0.01 market BUY (fills immediately)
    .venv/Scripts/python.exe tools/mt5_test_order.py status           # show test orders/positions and their expiry
    .venv/Scripts/python.exe tools/mt5_test_order.py cleanup          # remove/close everything this tool placed

Safety: refuses anything but a DEMO account, never logs in (attaches to the running terminal only) and never prints
the login or balance. While a test order or position exists on the symbol, the FVG executor will (correctly) refuse
new baskets because of existing exposure, so run `cleanup` when you are done.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings  # noqa: E402
from app.data.mt5 import terminal_running  # noqa: E402
from app.mt5_time import resolve_time_base  # noqa: E402

TEST_MAGIC = 761099           # FVG baskets use 761007; this tool's orders are never adopted by the FVG engine
TEST_COMMENT = "VC-TEST"
VOLUME = 0.01
EXPIRY = timedelta(hours=2)
SL_DISTANCE, TP_DISTANCE = 5.00, 10.00  # price units below/above the entry (1:2)


def fail(msg: str) -> None:
    print(f"STOPPED: {msg}")
    raise SystemExit(1)


def connect():
    import MetaTrader5 as mt5
    if terminal_running() is not True:
        fail("MetaTrader 5 is not running (or could not be verified); start it and log in first")
    if not mt5.initialize():  # attach to the running terminal; no credentials are passed
        fail(f"MT5 initialize failed: {mt5.last_error()}")
    acc, term = mt5.account_info(), mt5.terminal_info()
    if acc is None or term is None:
        fail("MT5 account/terminal information unavailable")
    if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        fail("this tool only runs on a DEMO account")
    settings = load_settings()
    symbol = settings.symbol
    if not symbol or mt5.symbol_info(symbol) is None:
        fail(f"symbol {symbol!r} is not available in this terminal")
    tb = resolve_time_base(acc.server, settings.mt5_server_utc_offset_hours)
    print(f"Account: {acc.server} (demo), {acc.currency}, hedging={acc.margin_mode == mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING}"
          f" | symbol {symbol} | time base UTC{tb.offset_hours:+g} h ({tb.source})")
    if not term.trade_allowed:
        fail("Algo Trading is OFF in the MT5 terminal (toolbar button)")
    return mt5, symbol, tb


def utc(tb, epoch) -> str:
    return tb.to_utc(epoch).strftime("%Y-%m-%d %H:%M:%S UTC") if epoch else "-"


def place(market: bool, distance: float) -> None:
    mt5, symbol, tb = connect()
    info, tick = mt5.symbol_info(symbol), mt5.symbol_info_tick(symbol)
    if tick is None or not tick.ask:
        fail("no current quote")
    digits = info.digits
    if market:
        price = tick.ask
        flags = info.filling_mode
        filling = (mt5.ORDER_FILLING_FOK if flags & 1 else mt5.ORDER_FILLING_IOC if flags & 2 else mt5.ORDER_FILLING_RETURN)
        request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": VOLUME, "type": mt5.ORDER_TYPE_BUY,
                   "price": price, "sl": round(price - SL_DISTANCE, digits), "tp": round(price + TP_DISTANCE, digits),
                   "deviation": 20, "magic": TEST_MAGIC, "comment": TEST_COMMENT, "type_filling": filling,
                   "type_time": mt5.ORDER_TIME_GTC}
        what = f"market BUY {VOLUME} at ~{price}"
    else:
        price = round(tick.ask - distance, digits)
        expires = datetime.now(timezone.utc) + EXPIRY
        request = {"action": mt5.TRADE_ACTION_PENDING, "symbol": symbol, "volume": VOLUME, "type": mt5.ORDER_TYPE_BUY_LIMIT,
                   "price": price, "sl": round(price - SL_DISTANCE, digits), "tp": round(price + TP_DISTANCE, digits),
                   "magic": TEST_MAGIC, "comment": TEST_COMMENT, "type_filling": mt5.ORDER_FILLING_RETURN,
                   "type_time": mt5.ORDER_TIME_SPECIFIED, "expiration": int(tb.to_broker(expires).timestamp())}
        what = f"BUY LIMIT {VOLUME} at {price} (Ask {tick.ask}), expiry {expires:%H:%M:%S} UTC"
    print(f"Request: {what}, SL {request['sl']}, TP {request['tp']}")
    check = mt5.order_check(request)
    print(f"order_check: retcode {getattr(check, 'retcode', None)} {getattr(check, 'comment', '')}")
    if check is None or check.retcode != 0:
        fail("broker preflight rejected the test order; nothing was sent")
    result = mt5.order_send(request)
    if result is None:
        fail(f"order_send returned nothing ({mt5.last_error()}); check MT5 before retrying")
    print(f"order_send: retcode {result.retcode} ({result.comment}) order {result.order} deal {result.deal}")
    if result.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
        fail("the broker did not accept the test order")
    print("OK - see it in MT5 > Trade tab. Then run `status`, and `cleanup` when done.")
    _show(mt5, symbol, tb)


def _show(mt5, symbol, tb) -> None:
    orders = [o for o in (mt5.orders_get(symbol=symbol) or ()) if o.magic == TEST_MAGIC]
    positions = [p for p in (mt5.positions_get(symbol=symbol) or ()) if p.magic == TEST_MAGIC]
    for o in orders:
        life = (o.time_expiration - o.time_setup) / 3600 if o.time_expiration and o.time_setup else None
        print(f"  pending #{o.ticket} {o.volume_current} @ {o.price_open} SL {o.sl} TP {o.tp} | set {utc(tb, o.time_setup)}"
              f" | expires {utc(tb, o.time_expiration)}" + (f" | lifetime {life:.2f} h (expected 2.00)" if life else ""))
    for p in positions:
        print(f"  position #{p.ticket} {p.volume} @ {p.price_open} SL {p.sl} TP {p.tp} | opened {utc(tb, p.time)}"
              f" | floating {p.profit:+.2f}")
    if not orders and not positions:
        print("  no test orders or positions")


def status() -> None:
    mt5, symbol, tb = connect()
    _show(mt5, symbol, tb)


def cleanup() -> None:
    mt5, symbol, tb = connect()
    for o in [o for o in (mt5.orders_get(symbol=symbol) or ()) if o.magic == TEST_MAGIC]:
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket, "magic": TEST_MAGIC})
        print(f"remove pending #{o.ticket}: retcode {getattr(r, 'retcode', None)} {getattr(r, 'comment', '')}")
    info = mt5.symbol_info(symbol)
    for p in [p for p in (mt5.positions_get(symbol=symbol) or ()) if p.magic == TEST_MAGIC]:
        tick = mt5.symbol_info_tick(symbol)
        flags = info.filling_mode
        filling = (mt5.ORDER_FILLING_FOK if flags & 1 else mt5.ORDER_FILLING_IOC if flags & 2 else mt5.ORDER_FILLING_RETURN)
        r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": p.volume, "position": p.ticket,
                            "type": mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                            "price": tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask, "deviation": 20,
                            "magic": TEST_MAGIC, "comment": TEST_COMMENT, "type_filling": filling})
        print(f"close position #{p.ticket}: retcode {getattr(r, 'retcode', None)} {getattr(r, 'comment', '')}")
    _show(mt5, symbol, tb)


def main() -> None:
    ap = argparse.ArgumentParser(description="Manual DEMO-only MT5 execution test (0.01 lot).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("place")
    p.add_argument("--market", action="store_true", help="market BUY instead of a BUY LIMIT")
    p.add_argument("--distance", type=float, default=5.0, help="BUY LIMIT distance below the Ask (price units)")
    sub.add_parser("status")
    sub.add_parser("cleanup")
    args = ap.parse_args()
    if args.cmd == "place":
        place(args.market, args.distance)
    elif args.cmd == "status":
        status()
    else:
        cleanup()


if __name__ == "__main__":
    main()
