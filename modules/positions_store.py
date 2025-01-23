import os
import json

STATE_FILE = "bot_state.json"

def load_state():
    """
    Stockage minimal: 
      {
        "did_daily_update_today": bool,
        "last_risk_check_ts": float,
        "positions_meta": {
          "BNB": {"entry_px":..., "did_skip_sell_once":..., "partial_sold":..., "max_price":...},
          ...
        }
      }
    """
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    else:
        st = {
            "did_daily_update_today": False,
            "last_risk_check_ts": 0.0,
            "positions_meta": {}
        }
        save_state(st)
        return st

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)