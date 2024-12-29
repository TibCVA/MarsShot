import os
import json
import yaml

STATE_FILE = "/app/bot_state.json"
CONFIG_FILE = "/app/config.yaml"

def load_state(initial_cap):
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE,"r") as f:
            st = json.load(f)
        return st
    else:
        st = {
            "positions": {},
            "capital": initial_cap,
            "capital_high": initial_cap,
            "losses_count": 0
        }
        save_state(st)
        return st

def save_state(state):
    with open(STATE_FILE,"w") as f:
        json.dump(state,f)

def get_symbol_for_token(sym):
    with open(CONFIG_FILE,"r") as f:
        c = yaml.safe_load(f)
    mapping = c["exchanges"]["binance"]["symbol_mapping"]
    if sym in mapping:
        return mapping[sym]
    return sym+"USDT"

