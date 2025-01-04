#!/usr/bin/env python3
# coding: utf-8

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime
from typing import Optional

# Import de la fonction qui calcule RSI, MACD, ATR
from indicators import compute_rsi_macd_atr

########################################
# CONFIGURATION GLOBALE
########################################

LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"   # <-- Remplacez par votre clé
SHIFT_DAYS = 2        # Label => +5% sur 2 jours
THRESHOLD = 0.05      # 0.05 => +5%
OUTPUT_CSV = "training_data.csv"
LOG_FILE   = "build_csv.log"

# Pour éviter le rate-limit (10 requêtes / minute)
SLEEP_BETWEEN_TOKENS = 6

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv ===")


########################################
# LISTE DES ~150 ALTCOINS
########################################

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
    {"symbol": "HIGH"},
    {"symbol": "PALM"},
    {"symbol": "DEXE"},
    {"symbol": "ATA"},
    {"symbol": "NOS"},
    {"symbol": "PRIME"},
    {"symbol": "HGPT"},
    {"symbol": "SPX"},
    {"symbol": "PAAL"},
    {"symbol": "POPCAT"},
    {"symbol": "LAT"},
    {"symbol": "PEAQ"},
    {"symbol": "PEPECOIN"},
    {"symbol": "BOBO"},
    {"symbol": "ALU"},
    {"symbol": "DENT"},
    {"symbol": "WOJAK"},
    {"symbol": "VANRY"},
    {"symbol": "CORE"},
    {"symbol": "UFT"},
    {"symbol": "TOSHI"},
    {"symbol": "SOLO"},
    {"symbol": "STG"},
    {"symbol": "BITCOIN"},
    {"symbol": "SCRT"},
    {"symbol": "RAY"},
    {"symbol": "VINU"},
    {"symbol": "WIF"},
    {"symbol": "CETUS"},
    {"symbol": "MNT"},
    {"symbol": "ELON"},
    {"symbol": "SUN"},
    {"symbol": "RENDER"},
    {"symbol": "MOG"},
    {"symbol": "IOTA"},
    {"symbol": "BSOL"},
    {"symbol": "JITOSOL"},
    {"symbol": "MSOL"},
    {"symbol": "SUPER"},
    {"symbol": "DUSK"},
    {"symbol": "CRV"},
    {"symbol": "TAO"},
    {"symbol": "AITECH"},
    {"symbol": "TEL"},
    {"symbol": "GRT"},
    {"symbol": "BORG"},
    {"symbol": "TOKEN"},
    {"symbol": "PHB"},
    {"symbol": "UNI"},
    {"symbol": "NPC"},
    {"symbol": "BEAM"},
    {"symbol": "ACS"},
    {"symbol": "SHIB"},
    {"symbol": "BGB"},
    {"symbol": "ASM"},
    {"symbol": "ADA"},
    {"symbol": "KAS"},
    {"symbol": "PEPE"},
    {"symbol": "AIDOGE"},
    {"symbol": "ARKM"},
    {"symbol": "DODO"},
    {"symbol": "ALPACA"},
    {"symbol": "AXS"},
    {"symbol": "LPT"},
    {"symbol": "AAVE"},
    {"symbol": "NKN"},
    {"symbol": "NEXO"},
    {"symbol": "VIDT"},
    {"symbol": "PIVX"},
    {"symbol": "RSR"},
    {"symbol": "ETC"},
    {"symbol": "ID"},
    {"symbol": "WTRX"},
    {"symbol": "DOGE"},
    {"symbol": "AIOZ"},
    {"symbol": "TRX"},
    {"symbol": "SUSHI"},
    {"symbol": "BAND"},
    {"symbol": "PENDLE"},
    {"symbol": "MYRO"},
    {"symbol": "CHEX"},
    {"symbol": "BANANA"},
    {"symbol": "AVAX"},
    {"symbol": "MPLX"},
    {"symbol": "SSV"},
    {"symbol": "TLM"},
    {"symbol": "LEASH"},
    {"symbol": "LIT"},
    {"symbol": "CHESS"},
    {"symbol": "HIFI"},
    {"symbol": "FLOKI"},
    {"symbol": "MTL"},
    {"symbol": "WSTETH"},
    {"symbol": "BTC.b"},
    {"symbol": "FLUX"},
    {"symbol": "RETH"},
    {"symbol": "VTHO"},
    {"symbol": "DIA"},
    {"symbol": "WETH"},
    {"symbol": "SLP"},
    {"symbol": "CTSI"},
    {"symbol": "weETH"},
    {"symbol": "HOT"},
    {"symbol": "COTI"},
    {"symbol": "MAPO"},
    {"symbol": "BTCB"},
    {"symbol": "TBTC"},
    {"symbol": "FUN"},
    {"symbol": "OKB"},
    {"symbol": "MLN"},
    {"symbol": "APT"},
    {"symbol": "BOBA"},
    {"symbol": "AGI"},
    {"symbol": "BEL"},
    {"symbol": "CKB"},
    {"symbol": "STRX"},
    {"symbol": "stETH"},
    {"symbol": "CTC"},
    {"symbol": "WBTC"},
    {"symbol": "PATRIOT"},
    {"symbol": "NUMO"},
    {"symbol": "LOFI"},
    {"symbol": "ELIZA"},
    {"symbol": "AVA"},
    {"symbol": "AXOL"},
    {"symbol": "UROA"},
    {"symbol": "KOMAINU"},
    {"symbol": "DASHA"},
    {"symbol": "LUNA"},
    {"symbol": "MEMESAI"},
    {"symbol": "MOO"},
    {"symbol": "DEBRIDGE"},
    {"symbol": "PUFFER"},
    {"symbol": "SNS"},
    {"symbol": "TOKENBOT"},
    {"symbol": "CHEEMS"},
    {"symbol": "ORDERLY"},
    {"symbol": "ZIRCUIT"},
    {"symbol": "CARV"}
]


########################################
# FONCTIONS UTILES
########################################

def fetch_lunar_data(symbol: str) -> Optional[pd.DataFrame]:
    """
    Récupère l'historique daily depuis l'endpoint:
      https://lunarcrush.com/api4/public/coins/<symbol>/time-series/v2
    Paramètres: bucket=day, interval=1y.

    Champs qu'on conserve:
      date, open, close, high, low, volume, market_cap,
      galaxy_score, alt_rank, sentiment
    """
    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": "1y"
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        logging.info(f"[LUNAR] {symbol} => HTTP {r.status_code}")

        if r.status_code != 200:
            logging.warning(f"[WARN] {symbol} => code={r.status_code}, skip.")
            return None

        j = r.json()
        if "data" not in j or not j["data"]:
            logging.warning(f"[WARN] {symbol} => data vide => skip.")
            return None

        rows = []
        for point in j["data"]:
            unix_ts = point.get("time")
            if not unix_ts:
                continue

            dt_utc = datetime.utcfromtimestamp(unix_ts)
            o      = point.get("open", None)
            c      = point.get("close", None)
            h      = point.get("high", None)
            lo     = point.get("low", None)
            vol_24 = point.get("volume_24h", None)
            mc     = point.get("market_cap", None)
            gal    = point.get("galaxy_score", None)
            alt_   = point.get("alt_rank", None)
            senti  = point.get("sentiment", None)

            rows.append([
                dt_utc, o, c, h, lo, vol_24, mc,
                gal, alt_, senti
            ])

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=[
            "date","open","close","high","low","volume","market_cap",
            "galaxy_score","alt_rank","sentiment"
        ])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # => plus de filtrage par heure
        return df

    except Exception as e:
        logging.error(f"[ERROR] {symbol} => {e}")
        return None


def compute_label(df: pd.DataFrame, days=2, threshold=0.05) -> pd.DataFrame:
    """
    Ajoute la colonne 'label' => 1 si le prix close augmente de +threshold sur N jours.
    """
    df = df.sort_values("date").reset_index(drop=True)
    if "close" not in df.columns:
        df["label"] = None
        return df

    df["future_close"] = df["close"].shift(-days)
    df["variation"] = (df["future_close"] - df["close"]) / df["close"]
    df["label"] = (df["variation"] >= threshold).astype(float)
    return df


def compute_daily_change(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """
    Calcule la variation journalière de la colonne 'close'.
    daily_change(t) = close(t)/close(t-1) - 1
    Stocke le résultat dans df[col_name].
    """
    df = df.sort_values("date").reset_index(drop=True)
    if "close" not in df.columns:
        df[col_name] = None
        return df

    df["prev_close"] = df["close"].shift(1)
    df[col_name] = (df["close"] / df["prev_close"] - 1).replace([float("inf"), -float("inf")], None)
    df.drop(columns=["prev_close"], inplace=True)
    return df


def main():
    logging.info("=== build_csv => Start (no hour filter, daily changes for BTC/ETH) ===")

    # 1) Récup data BTC + daily change
    df_btc = fetch_lunar_data("BTC")
    if df_btc is not None and not df_btc.empty:
        df_btc = compute_daily_change(df_btc, "btc_daily_change")
        df_btc = df_btc[["date","btc_daily_change"]]
    else:
        df_btc = pd.DataFrame(columns=["date","btc_daily_change"])

    # 2) Récup data ETH + daily change
    df_eth = fetch_lunar_data("ETH")
    if df_eth is not None and not df_eth.empty:
        df_eth = compute_daily_change(df_eth, "eth_daily_change")
        df_eth = df_eth[["date","eth_daily_change"]]
    else:
        df_eth = pd.DataFrame(columns=["date","eth_daily_change"])

    # 3) Boucle sur altcoins
    from indicators import compute_rsi_macd_atr

    all_dfs = []
    nb_tokens = len(TOKENS)

    for i, tk in enumerate(TOKENS, start=1):
        sym = tk["symbol"]
        logging.info(f"[ALT {i}/{nb_tokens}] => {sym}")
        df_alt = fetch_lunar_data(sym)
        if df_alt is None or df_alt.empty:
            logging.warning(f"[SKIP] {sym} => no data.")
            continue

        # Label (5% sur 2 jours)
        df_alt = compute_label(df_alt, SHIFT_DAYS, THRESHOLD)

        # RSI, MACD, ATR
        df_ind = compute_rsi_macd_atr(df_alt)

        # Copie du label
        df_ind["label"] = df_alt["label"]
        # On enlève les lignes sans label
        df_ind.dropna(subset=["label"], inplace=True)

        # Ajout 'symbol'
        df_ind["symbol"] = sym

        # Merge BTC
        merged = pd.merge(df_ind, df_btc, on="date", how="left")
        # Merge ETH
        merged = pd.merge(merged, df_eth, on="date", how="left")

        all_dfs.append(merged)

        # Anti rate-limit
        time.sleep(SLEEP_BETWEEN_TOKENS)

    if not all_dfs:
        # Aucun alt token n'a produit de data
        logging.warning("No alt data => minimal CSV.")
        columns = [
            "date","open","close","high","low","volume","market_cap",
            "galaxy_score","alt_rank","sentiment",
            "rsi","macd","atr",
            "label","symbol",
            "btc_daily_change","eth_daily_change"
        ]
        df_empty = pd.DataFrame(columns=columns)
        df_empty.to_csv(OUTPUT_CSV, index=False)
        print(f"[WARN] No data => minimal CSV => {OUTPUT_CSV}")
        return

    # 4) Concat final
    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    # Retrait de 'variation', 'future_close' si présents
    for col in ["variation","future_close"]:
        if col in df_final.columns:
            df_final.drop(columns=[col], inplace=True)

    # 5) Export CSV
    df_final.to_csv(OUTPUT_CSV, index=False)
    logging.info(f"Export => {OUTPUT_CSV} => {len(df_final)} rows")
    print(f"Export => {OUTPUT_CSV} ({len(df_final)} rows)")

    logging.info("=== DONE build_csv ===")


if __name__ == "__main__":
    main()