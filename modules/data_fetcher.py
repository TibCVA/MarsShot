import requests
import logging
import time
import os
import pandas as pd
from datetime import datetime, timedelta

from .indicators import compute_indicators

def fetch_data_for_all_tokens(tokens_list, config):
    """
    Renvoie un dict:
      { "SYM": { "features": { "price", "volume", "market_cap", "holders", "sentiment_score", "ATR", "RSI", "MACD" } } }
    """
    out = {}
    days_history = config["risk"].get("days_history", 30)

    for tk in tokens_list:
        sym = tk["symbol"]
        cmc_id = tk.get("cmc_id", None)
        chain = tk.get("nansen_chain", None)
        contract = tk.get("nansen_contract", None)
        lunar_sym = tk.get("lunar_symbol", None)

        # 1) CoinMarketCap => hist
        df_hist = fetch_coinmarketcap_history(cmc_id, days_history, config)
        if df_hist is None or df_hist.empty:
            logging.warning(f"No CMC data => skip {sym}")
            continue

        df_indic = compute_indicators(df_hist)
        last_row = df_indic.iloc[-1]

        # 2) holders => Nansen
        holders_val = fetch_nansen_holders(chain, contract, config)
        if holders_val is None:
            holders_val = 0

        # 3) sentiment => LunarCrush
        senti_val = fetch_lunar_sentiment(lunar_sym, config)
        if senti_val is None:
            senti_val = 0.5

        feats = {
            "price": last_row["close"],
            "volume": last_row["volume"],
            "market_cap": last_row["market_cap"],
            "holders": holders_val,
            "sentiment_score": senti_val,
            "ATR": last_row.get("ATR",0),
            "RSI": last_row.get("RSI",50),
            "MACD": last_row.get("MACD",0)
        }
        out[sym] = {"features": feats}
        time.sleep(2)  # anti rate-limit
    return out

def fetch_coinmarketcap_history(cmc_id, days, config):
    if not cmc_id:
        return None
    key = config["coinmarketcap"]["api_key"]
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
    headers = {
        "X-CMC_PRO_API_KEY": key,
        "Accepts": "application/json"
    }
    params = {
        "id": str(cmc_id),
        "time_start": start_date.isoformat(),
        "time_end": end_date.isoformat(),
        "interval": "1d",
        "count": days,
        "convert": "USD"
    }
    try:
        r = requests.get(url, headers=headers, params=params)
        j = r.json()
        if "data" not in j or not j["data"]:
            return None
        quotes = j["data"]["quotes"]
        if not quotes:
            return None
        rows = []
        for q in quotes:
            t = q["timestamp"]
            dd = datetime.fromisoformat(t.replace("Z",""))
            usd = q["quote"].get("USD", {})
            o = usd.get("open", None)
            h = usd.get("high", None)
            lo = usd.get("low", None)
            c = usd.get("close", None)
            vol = usd.get("volume", None)
            mc = usd.get("market_cap", None)
            if (o is None) or (h is None) or (lo is None) or (c is None):
                continue
            rows.append([dd,o,h,lo,c,vol,mc])
        df = pd.DataFrame(rows, columns=["date","open","high","low","close","volume","market_cap"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception as e:
        logging.error(f"[CMC ERROR] {cmc_id} => {e}")
        return None

def fetch_nansen_holders(chain, contract, config):
    if not chain or not contract:
        return None
    key = config["nansen"]["api_key"]
    url = f"https://api.nansen.ai/tokens/{chain}/{contract}/holders"
    headers = {"X-API-KEY": key}
    try:
        r = requests.get(url, headers=headers)
        j = r.json()
        if "data" in j and "holders" in j["data"]:
            return j["data"]["holders"]
        return None
    except:
        return None

def fetch_lunar_sentiment(symbol, config):
    if not symbol:
        return None
    key = config["lunarcrush"]["api_key"]
    url = f"https://lunarcrush.com/api2?symbol={symbol}&data=market"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        r = requests.get(url, headers=headers)
        j = r.json()
        if "data" not in j or not j["data"]:
            return None
        dd = j["data"][0]
        sc = dd.get("social_score", 50)
        maxi = max(sc,100)
        val = sc/maxi
        if val>1: val=1
        return val
    except:
        return None

def is_global_crash(config):
    return False

