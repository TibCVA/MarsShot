import os
import json

STATE_FILE = "bot_state.json"

def load_state():
    """
    On ne stocke plus capital_usdt ni positions, 
    seulement un champ "positions_meta": { "BNB": { "entry_px":..., ...}, ...}
    + did_daily_update_today, last_risk_check_ts, etc.
    """
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    else:
        st = {
            "did_daily_update_today": False,
            "last_risk_check_ts": 0,
            "positions_meta": {}  # store ephemeral info => partial_sold, max_price, ...
        }
        save_state(st)
        return st

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
