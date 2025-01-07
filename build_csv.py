#!/usr/bin/env python3
# coding: utf-8

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

# Import de la fonction qui calcule RSI, MACD, ATR
from indicators import compute_rsi_macd_atr

########################################
# CONFIG GLOBALE
########################################

LUNAR_API_KEY = "VOTRE_CLE_ICI"   # <-- Remplacez par votre clé valide
SHIFT_DAYS = 2                    # Label => +5% sur 2 jours
THRESHOLD = 0.05                  # +5%
OUTPUT_CSV = "training_data.csv"
LOG_FILE   = "build_csv.log"

# Pour limiter le rate-limit => on attend 12 s par token
# (5 tokens/min, 300 tokens ~ en 1h)
SLEEP_BETWEEN_TOKENS = 12

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv (2 ans, single-call) ===")

########################################
# LISTE DES 321 TOKENS
########################################

TOKENS = [
  {"symbol": "BTG"},
  {"symbol": "TRUMP"},
  {"symbol": "SBD"},
  {"symbol": "NCT"},
  {"symbol": "HIVE"},
  {"symbol": "PAAL"},
  {"symbol": "PRIME"},
  {"symbol": "STG"},
  {"symbol": "NOS"},
  {"symbol": "ACS"},
  {"symbol": "SFUND"},
  {"symbol": "CETUS"},
  {"symbol": "MAGIC"},
  {"symbol": "MCADE"},
  {"symbol": "ALU"},
  {"symbol": "CTXC"},
  {"symbol": "AI"},
  {"symbol": "BITCOIN"},
  {"symbol": "BLUE"},
  {"symbol": "SUSHI"},
  {"symbol": "DAR"},
  {"symbol": "TOSHI"},
  {"symbol": "WMTX"},
  {"symbol": "STEEM"},
  {"symbol": "AKT"},
  {"symbol": "XNO"},
  {"symbol": "CGPT"},
  {"symbol": "XCN"},
  {"symbol": "HUNT"},
  {"symbol": "KAVA"},
  {"symbol": "WAVES"},
  {"symbol": "LUNA"},
  {"symbol": "TEL"},
  {"symbol": "VANRY"},
  {"symbol": "WOO"},
  {"symbol": "NFP"},
  {"symbol": "SPELL"},
  {"symbol": "ARK"},
  {"symbol": "UMA"},
  {"symbol": "RSR"},
  {"symbol": "ASM"},
  {"symbol": "VRA"},
  {"symbol": "BANANA"},
  {"symbol": "OSMO"},
  {"symbol": "POPCAT"},
  {"symbol": "STRAX"},
  {"symbol": "PEAQ"},
  {"symbol": "sAVAX"},
  {"symbol": "BOBO"},
  {"symbol": "STPT"},
  {"symbol": "WAVAX"},
  {"symbol": "ZRX"},
  {"symbol": "DEXE"},
  {"symbol": "XEM"},
  {"symbol": "KNC"},
  {"symbol": "DGB"},
  {"symbol": "CTK"},
  {"symbol": "ARKM"},
  {"symbol": "ENJ"},
  {"symbol": "MOC"},
  {"symbol": "MAV"},
  {"symbol": "DENT"},
  {"symbol": "NTRN"},
  {"symbol": "ELF"},
  {"symbol": "ROSE"},
  {"symbol": "SUPER"},
  {"symbol": "HIFI"},
  {"symbol": "HIGH"},
  {"symbol": "SXP"},
  {"symbol": "RLC"},
  {"symbol": "ICX"},
  {"symbol": "BAT"},
  {"symbol": "VOXEL"},
  {"symbol": "ANKR"},
  {"symbol": "GAS"},
  {"symbol": "SKL"},
  {"symbol": "ONE"},
  {"symbol": "ALICE"},
  {"symbol": "SYN"},
  {"symbol": "GLM"},
  {"symbol": "AIDOGE"},
  {"symbol": "RVN"},
  {"symbol": "POLYX"},
  {"symbol": "SLP"},
  {"symbol": "QKC"},
  {"symbol": "SNT"},
  {"symbol": "CTSI"},
  {"symbol": "METIS"},
  {"symbol": "TRU"},
  {"symbol": "DASH"},
  {"symbol": "POWR"},
  {"symbol": "REI"},
  {"symbol": "AXL"},
  {"symbol": "RSS3"},
  {"symbol": "QTUM"},
  {"symbol": "BAND"},
  {"symbol": "BEL"},
  {"symbol": "ALCX"},
  {"symbol": "MTL"},
  {"symbol": "SOL"},
  {"symbol": "LINA"},
  {"symbol": "MOVR"},
  {"symbol": "MBOX"},
  {"symbol": "CHR"},
  {"symbol": "BAKE"},
  {"symbol": "1INCH"},
  {"symbol": "GRS"},
  {"symbol": "IOST"},
  {"symbol": "BNT"},
  {"symbol": "MVL"},
  {"symbol": "CFX"},
  {"symbol": "MOBILE"},
  {"symbol": "ELON"},
  {"symbol": "CYBER"},
  {"symbol": "ILV"},
  {"symbol": "ARDR"},
  {"symbol": "HFT"},
  {"symbol": "BONE"},
  {"symbol": "VELO"},
  {"symbol": "WAXP"},
  {"symbol": "ONT"},
  {"symbol": "DAO"},
  {"symbol": "BAL"},
  {"symbol": "LSK"},
  {"symbol": "XVS"},
  {"symbol": "ZIL"},
  {"symbol": "RIF"},
  {"symbol": "CBK"},
  {"symbol": "PHB"},
  {"symbol": "XYO"},
  {"symbol": "AL"},
  {"symbol": "BNX"},
  {"symbol": "DIA"},
  {"symbol": "WMATIC"},
  {"symbol": "RDNT"},
  {"symbol": "MATIC"},
  {"symbol": "XEC"},
  {"symbol": "DUSK"},
  {"symbol": "STORJ"},
  {"symbol": "NKN"},
  {"symbol": "COMP"},
  {"symbol": "GROK"},
  {"symbol": "AGI"},
  {"symbol": "AMP"},
  {"symbol": "ETHX"},
  {"symbol": "CELO"},
  {"symbol": "FLUX"},
  {"symbol": "BLUR"},
  {"symbol": "CVX"},
  {"symbol": "ETHDYDX"},
  {"symbol": "VIC"},
  {"symbol": "IQ"},
  {"symbol": "SNX"},
  {"symbol": "MINA"},
  {"symbol": "TURBO"},
  {"symbol": "LEVER"},
  {"symbol": "DEGO"},
  {"symbol": "UTK"},
  {"symbol": "ASTR"},
  {"symbol": "CXT"},
  {"symbol": "API3"},
  {"symbol": "ATLAS"},
  {"symbol": "LOOM"},
  {"symbol": "JOE"},
  {"symbol": "ACX"},
  {"symbol": "ORBS"},
  {"symbol": "HOT"},
  {"symbol": "CAKE"},
  {"symbol": "GMX"},
  {"symbol": "cbETH"},
  {"symbol": "CHESS"},
  {"symbol": "MLK"},
  {"symbol": "LUNC"},
  {"symbol": "LQTY"},
  {"symbol": "COTI"},
  {"symbol": "TKO"},
  {"symbol": "QI"},
  {"symbol": "vETH"},
  {"symbol": "FORTH"},
  {"symbol": "T"},
  {"symbol": "ALPHA"},
  {"symbol": "MBL"},
  {"symbol": "FIDA"},
  {"symbol": "CKB"},
  {"symbol": "TLM"},
  {"symbol": "PEPECOIN"},
  {"symbol": "YGG"},
  {"symbol": "APEX"},
  {"symbol": "AGLD"},
  {"symbol": "YFI"},
  {"symbol": "C98"},
  {"symbol": "CHZ"},
  {"symbol": "DKA"},
  {"symbol": "OMG"},
  {"symbol": "COS"},
  {"symbol": "ONG"},
  {"symbol": "SC"},
  {"symbol": "BIGTIME"},
  {"symbol": "ID"},
  {"symbol": "TROY"},
  {"symbol": "CHEX"},
  {"symbol": "CPOOL"},
  {"symbol": "ZEN"},
  {"symbol": "BSW"},
  {"symbol": "MPLX"},
  {"symbol": "STMX"},
  {"symbol": "NAKA"},
  {"symbol": "PRQ"},
  {"symbol": "PHA"},
  {"symbol": "JTO"},
  {"symbol": "VR"},
  {"symbol": "SD"},
  {"symbol": "TAI"},
  {"symbol": "REQ"},
  {"symbol": "AERGO"},
  {"symbol": "GOMINING"},
  {"symbol": "BDX"},
  {"symbol": "EURC"},
  {"symbol": "USDD"},
  {"symbol": "CHEEL"},
  {"symbol": "PYUSD"},
  {"symbol": "USDC.E"},
  {"symbol": "THE"},
  {"symbol": "CRVUSD"},
  {"symbol": "BUSD"},
  {"symbol": "FRAX"},
  {"symbol": "TUSD"},
  {"symbol": "CVC"},
  {"symbol": "ACA"},
  {"symbol": "BFC"},
  {"symbol": "vBNB"},
  {"symbol": "AA"},
  {"symbol": "BRISE"},
  {"symbol": "FIS"},
  {"symbol": "XAUt"},
  {"symbol": "BMX"},
  {"symbol": "ZEC"},
  {"symbol": "PAXG"},
  {"symbol": "FUN"},
  {"symbol": "MDT"},
  {"symbol": "AITECH"},
  {"symbol": "NMR"},
  {"symbol": "SSV"},
  {"symbol": "WPLS"},
  {"symbol": "BADGER"},
  {"symbol": "WHBAR"},
  {"symbol": "BETA"},
  {"symbol": "TLOS"},
  {"symbol": "JST"},
  {"symbol": "CSPR"},
  {"symbol": "BICO"},
  {"symbol": "NFT"},
  {"symbol": "COQ"},
  {"symbol": "POND"},
  {"symbol": "CELR"},
  {"symbol": "CLV"},
  {"symbol": "LIT"},
  {"symbol": "XCH"},
  {"symbol": "SAFE"},
  {"symbol": "HOOK"},
  {"symbol": "STRK"},
  {"symbol": "SFP"},
  {"symbol": "ORCA"},
  {"symbol": "RACA"},
  {"symbol": "ACH"},
  {"symbol": "TWT"},
  {"symbol": "LOOKS"},
  {"symbol": "ERN"},
  {"symbol": "SUN"},
  {"symbol": "TRAC"},
  {"symbol": "AVA"},
  {"symbol": "TRB"},
  {"symbol": "DATA"},
  {"symbol": "RIO"},
  {"symbol": "STRX"},
  {"symbol": "BTC.b"},
  {"symbol": "MX"},
  {"symbol": "IDEX"},
  {"symbol": "MEME"},
  {"symbol": "RARE"},
  {"symbol": "DF"},
  {"symbol": "RAD"},
  {"symbol": "IOTX"},
  {"symbol": "MED"},
  {"symbol": "KMD"},
  {"symbol": "OXT"},
  {"symbol": "TOKEN"},
  {"symbol": "CTC"},
  {"symbol": "GNO"},
  {"symbol": "EL"},
  {"symbol": "COW"},
  {"symbol": "PERP"},
  {"symbol": "VTHO"},
  {"symbol": "ACE"},
  {"symbol": "GHST"},
  {"symbol": "AUCTION"},
  {"symbol": "LOKA"},
  {"symbol": "TFUEL"},
  {"symbol": "XVG"},
  {"symbol": "SCRT"},
  {"symbol": "ATA"},
  {"symbol": "KSM"},
  {"symbol": "KDA"},
  {"symbol": "FXS"},
  {"symbol": "LRC"},
  {"symbol": "DIONE"},
  {"symbol": "PEOPLE"},
  {"symbol": "SATS"},
  {"symbol": "NPC"},
  {"symbol": "MYRO"},
  {"symbol": "ORDI"},
  {"symbol": "USTC"},
  {"symbol": "GNS"},
  {"symbol": "LADYS"},
  {"symbol": "ZETA"},
  {"symbol": "HPO"}
]

########################################
# FONCTION fetch_lunar_data_2y (single call)
########################################

def fetch_lunar_data_2y(symbol: str) -> Optional[pd.DataFrame]:
    """
    Récupère les données journalières du token (jusqu'à 2 ans)
    dans un SEUL appel.
    - start = now - 2 ans
    - end = now
    bucket=day
    => Si le token a moins d'1 an, on récupère quand même la période partielle.
    => Si le token a plus de 2 ans, on ne reçoit que 2 ans max (côté LunarCrush).
    """

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=730)  # 2 ans ~ 730 j

    start_ts = int(start_date.timestamp())
    end_ts   = int(end_date.timestamp())

    url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        # pas de interval=1y => on veut un "bucket=day" sur la période choisie
        "start": start_ts,  # en secondes
        "end":   end_ts     # en secondes
    }

    # On tente 2x en cas de code 429
    max_retries = 2
    attempt = 0
    df_out = None

    while attempt < max_retries:
        attempt += 1
        try:
            r = requests.get(url, params=params, timeout=30)
            logging.info(f"[LUNAR 2Y single] {symbol} => HTTP {r.status_code} (start={start_ts}, end={end_ts})")

            if r.status_code == 200:
                j = r.json()
                data_points = j.get("data", [])
                if data_points:
                    rows = []
                    for point in data_points:
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
                            dt_utc, o, c, h, lo, vol_24, mc, gal, alt_, senti
                        ])
                    if rows:
                        df_out = pd.DataFrame(rows, columns=[
                            "date","open","close","high","low","volume","market_cap",
                            "galaxy_score","alt_rank","sentiment"
                        ])
                break  # on sort du while (peu importe data ou non)
            elif r.status_code == 429:
                logging.warning(f"[WARN] {symbol} => 429 Too Many Requests => wait & retry attempt {attempt}")
                time.sleep(60)  # on attend 60s puis retente
            else:
                logging.warning(f"[WARN] {symbol} => code={r.status_code}, skip.")
                break
        except Exception as e:
            logging.error(f"[ERROR] {symbol} => {e}")
            break

    if df_out is None or df_out.empty:
        return None

    # tri date, remove duplicates
    df_out.sort_values("date", inplace=True)
    df_out.drop_duplicates(subset=["date"], keep="first", inplace=True)
    df_out.reset_index(drop=True, inplace=True)

    return df_out

########################################
# FONCTIONS UTILES (IDENTIQUES)
########################################

def compute_label(df: pd.DataFrame, days=2, threshold=0.05) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True)
    if "close" not in df.columns:
        df["label"] = None
        return df
    df["future_close"] = df["close"].shift(-days)
    df["variation"] = (df["future_close"] - df["close"]) / df["close"]
    df["label"] = (df["variation"] >= threshold).astype(float)
    return df

def compute_daily_change(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True)
    if "close" not in df.columns:
        df[col_name] = None
        return df
    df["prev_close"] = df["close"].shift(1)
    df[col_name] = (df["close"] / df["prev_close"] - 1).replace([float("inf"), -float("inf")], None)
    df.drop(columns=["prev_close"], inplace=True)
    return df

########################################
# MAIN
########################################

def main():
    logging.info("=== build_csv (2 ans, single-call) => Start ===")

    # Récup BTC (2 ans ou partiel) + daily change
    df_btc = fetch_lunar_data_2y("BTC")
    if df_btc is not None and not df_btc.empty:
        df_btc = compute_daily_change(df_btc, "btc_daily_change")
        df_btc = df_btc[["date","btc_daily_change"]]
    else:
        df_btc = pd.DataFrame(columns=["date","btc_daily_change"])

    # Récup ETH + daily change
    df_eth = fetch_lunar_data_2y("ETH")
    if df_eth is not None and not df_eth.empty:
        df_eth = compute_daily_change(df_eth, "eth_daily_change")
        df_eth = df_eth[["date","eth_daily_change"]]
    else:
        df_eth = pd.DataFrame(columns=["date","eth_daily_change"])

    # Récup SOL + daily change
    df_sol = fetch_lunar_data_2y("SOL")
    if df_sol is not None and not df_sol.empty:
        df_sol = compute_daily_change(df_sol, "sol_daily_change")
        df_sol = df_sol[["date","sol_daily_change"]]
    else:
        df_sol = pd.DataFrame(columns=["date","sol_daily_change"])

    # Boucle sur altcoins
    from indicators import compute_rsi_macd_atr

    all_dfs = []
    nb_tokens = len(TOKENS)

    for i, tk in enumerate(TOKENS, start=1):
        sym = tk["symbol"]
        logging.info(f"[ALT {i}/{nb_tokens}] => {sym}")

        df_alt = fetch_lunar_data_2y(sym)
        if df_alt is None or df_alt.empty:
            logging.warning(f"[SKIP] {sym} => no data.")
            continue

        # Label => +5% sur 2 jours
        df_alt = compute_label(df_alt, SHIFT_DAYS, THRESHOLD)

        # RSI, MACD, ATR
        df_ind = compute_rsi_macd_atr(df_alt)

        # Récupération du label
        df_ind["label"] = df_alt["label"]
        df_ind.dropna(subset=["label"], inplace=True)

        # Ajout du symbol
        df_ind["symbol"] = sym

        # Merge BTC
        merged = pd.merge(df_ind, df_btc, on="date", how="left")
        # Merge ETH
        merged = pd.merge(merged, df_eth, on="date", how="left")
        # Merge SOL
        merged = pd.merge(merged, df_sol, on="date", how="left")

        all_dfs.append(merged)

        # Pause anti rate-limit
        time.sleep(SLEEP_BETWEEN_TOKENS)

    if not all_dfs:
        # Rien du tout => CSV vide
        logging.warning("No alt data => minimal CSV.")
        columns = [
            "date","open","close","high","low","volume","market_cap",
            "galaxy_score","alt_rank","sentiment",
            "rsi","macd","atr",
            "label","symbol",
            "btc_daily_change","eth_daily_change","sol_daily_change"
        ]
        df_empty = pd.DataFrame(columns=columns)
        df_empty.to_csv(OUTPUT_CSV, index=False)
        print(f"[WARN] No data => minimal CSV => {OUTPUT_CSV}")
        return

    # Concat final
    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    # Supprime 'variation', 'future_close' si présents
    for col in ["variation","future_close"]:
        if col in df_final.columns:
            df_final.drop(columns=[col], inplace=True)

    # Export CSV
    df_final.to_csv(OUTPUT_CSV, index=False)
    logging.info(f"Export => {OUTPUT_CSV} => {len(df_final)} rows")
    print(f"Export => {OUTPUT_CSV} ({len(df_final)} rows)")

    logging.info("=== DONE build_csv (2 ans, single-call) ===")

if __name__ == "__main__":
    main()