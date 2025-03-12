#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
auto_select_tokens.py
---------------------
Sélectionne automatiquement les 60 meilleurs tokens "moonshot" basés sur
leur performance 24h, 7j et 30j, avec des pondérations plus fortes sur
le 7 jours et le 30 jours, pour un effet momentum + tendance.
Ensuite, une vérification de cohérence des daily close J-1 entre Binance et LunarCrush
est réalisée : si l’écart est supérieur à 5%, le token est exclu.
"""

import os
import yaml
import logging
import time
import requests
from datetime import datetime, timedelta

from binance.client import Client

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_YML = os.path.join(BASE_DIR, "config.yaml")
LOG_FILE   = "auto_select_tokens.log"

def fetch_usdt_spot_pairs(client):
    """
    Récupère toutes les paires Spot en USDT sur Binance,
    en filtrant les tokens indésirables (UP,DOWN,BULL,BEAR, stablecoins).
    """
    info = client.get_exchange_info()
    all_symbols = info.get("symbols", [])
    pairs = []
    for s in all_symbols:
        if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
            base = s.get("baseAsset","")
            # Exclusion: LEVERAGED tokens
            if any(x in base for x in ["UP","DOWN","BULL","BEAR"]):
                continue
            # Exclusion: stablecoins
            if base in ["USDC","BUSD","TUSD","USDT"]:
                continue
            pairs.append(s["symbol"])
    return pairs

def get_24h_change(client, symbol):
    """
    Retourne la variation sur 24h en % (ex: +5% => 0.05), ou 0.0 si problème.
    """
    try:
        tick = client.get_ticker(symbol=symbol)
        pc_str = tick.get("priceChangePercent","0")
        return float(pc_str)/100.0
    except:
        return 0.0

def get_kline_change(client, symbol, days=7):
    """
    Retourne la variation sur 'days' jours (ex: +10% => 0.10)
    en se basant sur des klines journalières. 0.0 si problème ou data insuffisante.
    """
    limit = days+5
    try:
        klines = client.get_klines(
            symbol=symbol,
            interval=Client.KLINE_INTERVAL_1DAY,
            limit=limit
        )
        if len(klines) <= days:
            return 0.0
        last_close = float(klines[-1][4])
        old_close  = float(klines[-days-1][4])
        if old_close <= 0:
            return 0.0
        return (last_close - old_close)/old_close
    except:
        return 0.0

def compute_token_score(p24, p7, p30):
    """
    Nouveau scoring "moonshot" :
      - 50% sur la perf 7 jours (momentum hebdo)
      - 30% sur la perf 30 jours (tendance plus durable)
      - 20% sur la perf 24h (volatilité court terme)
    """
    return 0.8*p7 + 0*p30 + 0.2*p24

def select_top_tokens(client, top_n=60):
    """
    Récupère la liste de toutes les paires USDT, calcule la perf 24h, 7j, 30j,
    et applique compute_token_score pour ranker. On renvoie les top_n tokens
    sous forme de baseAsset (ex: BNB si BNBUSDT).
    """
    all_pairs = fetch_usdt_spot_pairs(client)
    logging.info(f"[AUTO] fetch_usdt_spot_pairs => {len(all_pairs)} pairs")

    results = []
    count = 0
    for sym in all_pairs:
        count += 1
        if (count % 20) == 0:
            time.sleep(1)

        p24  = get_24h_change(client, sym)
        p7   = get_kline_change(client, sym, 7)
        p30  = get_kline_change(client, sym, 30)
        score = compute_token_score(p24, p7, p30)
        results.append((sym, score))

    # On trie du plus grand score au plus faible
    results.sort(key=lambda x: x[1], reverse=True)
    top = results[:top_n]

    # On renvoie la baseAsset (ex: BNB pour BNBUSDT)
    bases = []
    for sym, sc in top:
        if sym.endswith("USDT"):
            base = sym.replace("USDT", "")
            bases.append(base)
    return bases

def update_config_tokens_daily(new_tokens):
    """
    Met à jour la clé 'tokens_daily' dans config.yaml en y mettant new_tokens.
    """
    if not os.path.exists(CONFIG_YML):
        logging.warning(f"[update_config_tokens_daily] {CONFIG_YML} introuvable")
        return
    with open(CONFIG_YML, "r") as f:
        cfg = yaml.safe_load(f)
    cfg["tokens_daily"] = new_tokens

    with open(CONFIG_YML, "w") as f:
        yaml.dump(cfg, f, sort_keys=False)
    logging.info(f"[update_config_tokens_daily] => {len(new_tokens)} tokens => {new_tokens}")

# --- Nouvelle section pour la vérification de cohérence des daily close ---

def get_daily_close_binance(token, binance_client):
    """
    Récupère le prix de clôture J-1 depuis Binance pour token (en USDT).
    """
    symbol = token + "USDT"
    try:
        klines = binance_client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1DAY, limit=2)
        if len(klines) < 2:
            logging.warning(f"Pas assez de données pour {symbol} sur Binance.")
            return None
        # Le dernier kline est en cours, l'avant-dernier correspond à J-1.
        yesterday_close = float(klines[-2][4])
        return yesterday_close
    except Exception as e:
        logging.error(f"Erreur get_daily_close_binance pour {token}: {e}")
        return None

def get_daily_close_lunar(token, config):
    """
    Récupère le prix de clôture J-1 depuis LunarCrush pour token.
    """
    LUNAR_API_KEY = config.get("lunarcrush", {}).get("api_key", "")
    if not LUNAR_API_KEY:
        logging.warning("Clé LunarCrush manquante dans la config.")
        return None
    now_utc = datetime.utcnow()
    today_midnight = datetime(now_utc.year, now_utc.month, now_utc.day)
    yesterday_midnight = today_midnight - timedelta(days=1)
    start_ts = int(yesterday_midnight.timestamp())
    end_ts = int(today_midnight.timestamp())
    url = f"https://lunarcrush.com/api4/public/coins/{token}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "start": start_ts,
        "end": end_ts
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            logging.warning(f"LunarCrush API status code {r.status_code} pour {token}")
            return None
        data = r.json().get("data", [])
        if not data:
            logging.warning(f"Aucune donnée LunarCrush pour {token}")
            return None
        # On prend le dernier candle retourné
        candle = data[-1]
        close = candle.get("close")
        if close is None:
            return None
        return float(close)
    except Exception as e:
        logging.error(f"Erreur get_daily_close_lunar pour {token}: {e}")
        return None

def verify_token_consistency(tokens, config, binance_client, threshold=0.05):
    """
    Vérifie que le daily close J-1 entre Binance et LunarCrush ne diffère pas de plus de threshold (5% par défaut).
    Exclut les tokens pour lesquels l'écart est supérieur.
    """
    verified_tokens = []
    for token in tokens:
        close_binance = get_daily_close_binance(token, binance_client)
        close_lunar = get_daily_close_lunar(token, config)
        if close_binance is None or close_lunar is None:
            logging.info(f"Token {token} exclu : données manquantes (Binance: {close_binance}, LunarCrush: {close_lunar})")
            continue
        diff_ratio = abs(close_binance - close_lunar) / close_binance
        if diff_ratio <= threshold:
            verified_tokens.append(token)
        else:
            logging.info(f"Token {token} exclu : incohérence des données (Binance: {close_binance}, LunarCrush: {close_lunar}, diff: {diff_ratio:.2%})")
    return verified_tokens

def main():
    if not os.path.exists(CONFIG_YML):
        logging.error(f"[ERREUR] {CONFIG_YML} introuvable.")
        return

    with open(CONFIG_YML, "r") as f:
        config = yaml.safe_load(f)

    logging.basicConfig(
        filename=config["logging"]["file"],
        filemode='a',
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info("[MAIN] Starting auto_select_tokens.")

    if not config.get("binance_api", {}).get("api_key") or not config.get("binance_api", {}).get("api_secret"):
        logging.error("[ERROR] Clé/secret Binance manquante.")
        print("[ERROR] Clé/secret Binance manquante.")
        return

    key = config["binance_api"]["api_key"]
    sec = config["binance_api"]["api_secret"]
    client = Client(key, sec)

    # Sélection initiale des 60 tokens
    best60 = select_top_tokens(client, top_n=60)
    logging.info(f"[AUTO] Tokens initialement sélectionnés: {best60}")

    # Vérification de cohérence entre Binance et LunarCrush
    verified_tokens = verify_token_consistency(best60, config, client)
    logging.info(f"[AUTO] Tokens vérifiés et retenus: {verified_tokens}")

    # Mise à jour de la configuration avec la liste validée (peut contenir moins de 60 tokens)
    update_config_tokens_daily(verified_tokens)
    logging.info("[OK] auto_select_tokens => config.yaml updated")

if __name__=="__main__":
    main()