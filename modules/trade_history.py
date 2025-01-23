# modules/trade_history.py

import os, json, time, datetime

TRADE_HISTORY_FILE = "trade_history.json"

def load_trade_history():
    if not os.path.exists(TRADE_HISTORY_FILE):
        return []
    with open(TRADE_HISTORY_FILE,"r") as f:
        return json.load(f)

def save_trade_history(trades):
    with open(TRADE_HISTORY_FILE,"w") as f:
        json.dump(trades, f, indent=2)

def record_trade(side, symbol, qty, cost, avg_px):
    trades = load_trade_history()
    now_ts = int(time.time())
    trades.append({
        "timestamp": now_ts,
        "datetime": datetime.datetime.utcfromtimestamp(now_ts).isoformat(),
        "side": side.upper(),  # "BUY"/"SELL"
        "symbol": symbol,
        "qty": qty,
        "cost_usd": cost,
        "avg_px": avg_px
    })
    save_trade_history(trades)