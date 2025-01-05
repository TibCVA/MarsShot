import os
import json

STATE_FILE = "bot_state.json"

def load_state(initial_cap):
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    else:
        st = {
            "capital_usdt": initial_cap,
            "positions": {},
            "did_daily_update_today": False,
            "last_risk_check_ts": 0
        }
        save_state(st)
        return st

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)