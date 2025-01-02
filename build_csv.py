#!/usr/bin/env python3
# coding: utf-8

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime
from typing import Optional

# On importe notre module indicators.py (qui contient compute_rsi_macd_atr)
from indicators import compute_rsi_macd_atr

#####################################
# PARAMÈTRES GLOBAUX
#####################################

LUNAR_API_KEY = "VOTRE_CLE_API_LUNAR"
# Exemple: "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"
# Remplacez par votre clé

SHIFT_DAYS = 2      # Délai pour calculer le label (hausse sur 2 jours)
THRESHOLD = 0.05    # Seuil de hausse => label=1 si +5% par ex.

OUTPUT_CSV = "training_data.csv"
LOG_FILE = "build_csv.log"

SLEEP_BETWEEN_TOKENS = 6  # 6 secondes entre chaque token pour éviter le rate-limit

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv ===")


#####################################
# LISTE DE TOKENS ALT
#####################################
TOKENS = [
    {"symbol": "GOAT"},
    {"symbol": "FARTCOIN"},
    {"symbol": "ZEREBRO"},
    {"symbol": "STNK"},
    {"symbol": "BONK"},
    {"symbol": "FET"},
    {"symbol": "AGIX"},
    {"symbol": "NMR"},
    {"symbol": "CTXC"},
    {"symbol": "VLX"},
    {"symbol": "VET"},
    {"symbol": "CHZ"},
    {"symbol": "ENJ"},
    {"symbol": "MANA"},
    {"symbol": "SAND"},
    {"symbol": "INJ"},
    {"symbol": "WOO"},
    {"symbol": "OP"},
    {"symbol": "ARB"},
    {"symbol": "SNX"},
    {"symbol": "LDO"},
    {"symbol": "RUNE"},
    {"symbol": "RVF"},
    {"symbol": "ROSE"},
    {"symbol": "ALGO"},
    {"symbol": "GALA"},
    {"symbol": "SUI"},
    {"symbol": "QNT"},
    {"symbol": "LINK"},
    {"symbol": "SOLVEX"},
    {"symbol": "COOKIE"},
    {"symbol": "A8"},
    {"symbol": "PRQ"},
    {"symbol": "PHA"},
    {"symbol": "XYO"},
    {"symbol": "MCADE"},
    {"symbol": "COW"},
    {"symbol": "AVA"},
    {"symbol": "DF"},
    {"symbol": "XVG"},
    {"symbol": "AGLD"},
    {"symbol": "WILD"},
    {"symbol": "CPOOL"},
    {"symbol": "ZEN"},
    {"symbol": "UTK"},
    {"symbol": "WHBAR"},
    {"symbol": "SHIBTC"},
    {"symbol": "NCT"},
    {"symbol": "SRX"},
    {"symbol": "OMI"},
    {"symbol": "ACX"},
    {"symbol": "ARTY"},
    {"symbol": "FIRO"},
    {"symbol": "VELO"},
    {"symbol": "SWFTC"},
    {"symbol": "CXT"},
    {"symbol": "ZENT"},
    {"symbol": "IDEX"},
    {"symbol": "DFI"},
    {"symbol": "NEON"},
    {"symbol": "MUBI"},
    {"symbol": "BLZ"},
    {"symbol": "FT"},
    {"symbol": "MCOIN"},
    {"symbol": "RDNT"},
    {"symbol": "PDA"},
    {"symbol": "MYRIA"},
    {"symbol": "SATS"},
    {"symbol": "ACE"},
    {"symbol": "OLAS"},
    {"symbol": "AA"},
    {"symbol": "STT"},
    {"symbol": "MOBILE"},
    {"symbol": "ZTX"},
    {"symbol": "WEMIX"},
    {"symbol": "DAO"},
    {"symbol": "OSMO"},
    {"symbol": "BIGTIME"},
    {"symbol": "NTRN"},
    {"symbol": "CSPR"},
    {"symbol": "ISLM"},
    {"symbol": "NFP"},
    {"symbol": "TIA"},
    {"symbol": "HOOK"},
    {"symbol": "ORDI"},
    {"symbol": "PYR"},
    {"symbol": "TRB"},
    {"symbol": "10SET"},
    {"symbol": "GNS"},
    {"symbol": "RPL"},
    {"symbol": "MAGIC"},
    {"symbol": "MINA"},
    {"symbol": "OMG"},
    {"symbol": "SHDW"},
    {"symbol": "MEME"},
    {"symbol": "FXS"},
    {"symbol": "CFG"},
    {"symbol": "SBD"},
    {"symbol": "ILV"},
    {"symbol": "ASTR"},
    {"symbol": "REN"},
    {"symbol": "GMT"},
    {"symbol": "BTG"},
    {"symbol": "LINA"},
    {"symbol": "WMATIC"},
    {"symbol": "REEF"},
    {"symbol": "CYBER"},
    {"symbol": "BAKE"},
    {"symbol": "METIS"},
    {"symbol": "MBOX"},
    {"symbol": "VIC"},
    {"symbol": "ETHDYDX"},
    {"symbol": "HT"},
    {"symbol": "DYDX"},
    {"symbol": "EGLD"},
    {"symbol": "GMX"},
    {"symbol": "WOO"},
    {"symbol": "MAV"},
    {"symbol": "LUNA"},
    {"symbol": "MOVR"},
    {"symbol": "BSV"},
    {"symbol": "VR"},
    {"symbol": "KAVA"},
    {"symbol": "BLUR"},
    {"symbol": "AL"},
    {"symbol": "COMBO"},
    {"symbol": "HFT"},
    {"symbol": "GTC"},
    {"symbol": "VRA"},
    {"symbol": "GLMR"},
    {"symbol": "LOOM"},
    {"symbol": "ARK"},
    {"symbol": "XRD"},
    {"symbol": "ENJ"},
    {"symbol": "XCH"},
    {"symbol": "WAVES"},
    {"symbol": "AXL"},
    {"symbol": "BAL"},
    {"symbol": "BETA"},
    {"symbol": "NAKA"},
    {"symbol": "ATOM"},
    {"symbol": "JOE"},
    {"symbol": "SEI"},
    {"symbol": "WAXP"},
    {"symbol": "PERP"},
    {"symbol": "CTXC"},
    {"symbol": "CLORE"},
    {"symbol": "HARD"},
    {"symbol": "ATLAS"},
    {"symbol": "ALCX"},
    {"symbol": "ROSE"},
    {"symbol": "WLD"},
    {"symbol": "PROPC"},
    {"symbol": "AI"},
    {"symbol": "AKT"},
    {"symbol": "CVX"},
    {"symbol": "DGB"},
    {"symbol": "XNO"},
    {"symbol": "LQTY"},
    {"symbol": "INF"},
    {"symbol": "SOL"},
    {"symbol": "RVN"},
    {"symbol": "RLC"},
    {"symbol": "RSS3"},
    {"symbol": "DAG"},
    {"symbol": "RIO"},
    {"symbol": "ORAI"},
    {"symbol": "BLUE"},
    {"symbol": "sAVAX"},
    {"symbol": "WAVAX"},
    {"symbol": "CGPT"},
    {"symbol": "TKO"},
    {"symbol": "BNT"},
    {"symbol": "SFP"},
    {"symbol": "RIF"},
    {"symbol": "BONE"},
    {"symbol": "TRU"},
    {"symbol": "CHR"},
    {"symbol": "ONE"},
    {"symbol": "LADYS"},
    {"symbol": "QI"},
    {"symbol": "GNO"},
    {"symbol": "PROM"},
    {"symbol": "FIS"},
    {"symbol": "WIN"},
    {"symbol": "ZRX"},
    {"symbol": "FIDA"},
    {"symbol": "API3"},
    {"symbol": "ELF"},
    {"symbol": "ACH"},
    {"symbol": "HIGH"}
]
# Vous pouvez en ajouter davantage si besoin.

#####################################
# FONCTIONS
#####################################

def fetch_lunar_data(symbol: str) -> Optional[pd.DataFrame]:
    """
    Récupère l'historique (time-series v2) depuis LunarCrush pour un 'symbol'.
    On fixe bucket=day, interval=1y.
    On récupère: date, open, close, high, low, volume_24h, market_cap,
                 galaxy_score, alt_rank, sentiment
    On ne garde que les lignes correspondant aux heures 0h,12h,23h (pour n'avoir
    qu'1 ou 3 relevés par jour). Puis on renvoie un DataFrame ou None.
    """

    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": "1y"
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        logging.info(f"[LUNAR] symbol={symbol}, status={r.status_code}")
        if r.status_code != 200:
            logging.warning(f"[LUNAR WARNING] {symbol} => HTTP={r.status_code}, skip.")
            return None

        j = r.json()
        if "data" not in j or not j["data"]:
            logging.warning(f"[LUNAR WARNING] {symbol} => pas de data => skip.")
            return None

        rows = []
        for point in j["data"]:
            unix_ts = point.get("time")
            if not unix_ts:
                continue
            dt_utc = datetime.utcfromtimestamp(unix_ts)

            o    = point.get("open", None)
            c    = point.get("close", None)
            h    = point.get("high", None)
            lo   = point.get("low", None)
            vol  = point.get("volume_24h", None)
            mc   = point.get("market_cap", None)
            gal  = point.get("galaxy_score", None)
            alt_ = point.get("alt_rank", None)
            sent = point.get("sentiment", None)

            rows.append([
                dt_utc, o, c, h, lo, vol, mc,
                gal, alt_, sent
            ])

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=[
            "date","open","close","high","low","volume","market_cap",
            "galaxy_score","alt_rank","sentiment"
        ])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # On ne conserve qu'1 (ou 3) relevé(s) par jour => ex. 0h,12h,23h
        df["hour"] = df["date"].dt.hour
        df = df[df["hour"].isin([0,12,23])]
        df.drop(columns=["hour"], inplace=True, errors="ignore")

        return df

    except Exception as e:
        logging.error(f"[LUNAR ERROR] symbol={symbol} => {e}")
        return None


def compute_label(df: pd.DataFrame, shift_days=2, threshold=0.05) -> pd.DataFrame:
    """
    Ajoute une colonne 'label' => 1 si (future_close - close)/close >= threshold
    On calcule future_close = close.shift(-shift_days).
    """
    df = df.sort_values("date").reset_index(drop=True)
    if "close" not in df.columns:
        df["label"] = None
        return df
    df["future_close"] = df["close"].shift(-shift_days)
    df["variation"] = (df["future_close"] - df["close"]) / df["close"]
    df["label"] = (df["variation"] >= threshold).astype(float)
    return df


def compute_daily_change(df: pd.DataFrame, col_name="daily_change") -> pd.DataFrame:
    """
    Calcule la variation journalière du prix de clôture (ex: close(t)/close(t-1) - 1).
    Hypothèse: df est trié par date. On crée une colonne 'col_name'.
    ATTENTION: On utilise le close => daily_change(t) = (close(t) / close(t-1) -1)
    """
    df = df.sort_values("date").reset_index(drop=True)
    df[col_name] = None
    if "close" not in df.columns:
        return df

    # On fait un shift(1) => close(t-1) => on calcule la variation
    df["prev_close"] = df["close"].shift(1)
    df[col_name] = df.apply(
        lambda row: (row["close"] / row["prev_close"] - 1) if row["prev_close"] else None,
        axis=1
    )
    df.drop(columns=["prev_close"], inplace=True)
    return df


def main():
    logging.info("=== build_csv => collecting data + indicators + BTC/ETH daily change ===")

    # 1) On commence par récupérer l'historique BTC
    df_btc = fetch_lunar_data("BTC")
    if df_btc is None or df_btc.empty:
        logging.warning("Pas de data BTC => on continue quand même, btc_daily_change sera NaN.")
        df_btc = pd.DataFrame(columns=["date","btc_daily_change"])

    else:
        # Calcul du daily_change pour BTC
        df_btc = compute_daily_change(df_btc, col_name="btc_daily_change")
        # On ne garde que date + btc_daily_change
        df_btc = df_btc[["date","btc_daily_change"]].copy()

    # 2) Pareil pour ETH
    df_eth = fetch_lunar_data("ETH")
    if df_eth is None or df_eth.empty:
        logging.warning("Pas de data ETH => on continue quand même, eth_daily_change sera NaN.")
        df_eth = pd.DataFrame(columns=["date","eth_daily_change"])
    else:
        df_eth = compute_daily_change(df_eth, col_name="eth_daily_change")
        df_eth = df_eth[["date","eth_daily_change"]].copy()

    # 3) On va construire la liste des dataframes finaux
    all_dfs = []
    nb_tokens = len(TOKENS)

    for i, tk in enumerate(TOKENS, start=1):
        sym = tk["symbol"]
        logging.info(f"[{i}/{nb_tokens}] => symbol={sym}")

        # Récup data alt
        df_lunar = fetch_lunar_data(sym)
        if df_lunar is None or df_lunar.empty:
            logging.warning(f"No data for {sym}, skipping.")
            continue

        # Label
        df_lunar = compute_label(df_lunar, SHIFT_DAYS, THRESHOLD)

        # RSI, MACD, ATR
        df_indic = compute_rsi_macd_atr(df_lunar)

        # On recopie label
        df_indic["label"] = df_lunar["label"]
        # On dropna label
        df_indic.dropna(subset=["label"], inplace=True)

        # On ajoute la colonne symbol
        df_indic["symbol"] = sym

        # Merge with BTC daily change
        # => On fait un merge "left" sur la date
        # => Les dates n'ayant pas de correspondance BTC => btc_daily_change = NaN
        df_merged = pd.merge(
            df_indic, df_btc,
            on="date",
            how="left"
        )

        # Merge with ETH daily change
        df_merged = pd.merge(
            df_merged, df_eth,
            on="date",
            how="left"
        )

        # Tout est prêt, on l'ajoute à la liste
        all_dfs.append(df_merged)

        time.sleep(SLEEP_BETWEEN_TOKENS)

    # 4) Concat final
    if not all_dfs:
        logging.warning("No data => no CSV final.")
        print("No data => no CSV => check logs.")
        return

    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    # On retire variation/future_close si elles existent
    for col in ["variation","future_close"]:
        if col in df_final.columns:
            df_final.drop(columns=[col], inplace=True, errors="ignore")

    # 5) Export
    df_final.to_csv(OUTPUT_CSV, index=False)
    logging.info(f"Export => {OUTPUT_CSV} => {len(df_final)} rows")
    print(f"Export => {OUTPUT_CSV} ({len(df_final)} rows)")

    logging.info("=== DONE build_csv with BTC/ETH daily change ===")


if __name__ == "__main__":
    main()