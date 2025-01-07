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
# CONFIGURATION GLOBALE
########################################

LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"  # <-- Remplacez par votre clé
SHIFT_DAYS = 2         # Label => +5% sur 2 jours
THRESHOLD = 0.05       # 0.05 => +5%
OUTPUT_CSV = "training_data.csv"
LOG_FILE   = "build_csv.log"

# Pour éviter le rate-limit (10 requêtes / minute)
SLEEP_BETWEEN_TOKENS = 6

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv (2 ans) ===")

########################################
# LISTE DES 321 ALTCOINS
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
# FONCTION DE RÉCUP 2 ANS AVEC START/END
########################################

def fetch_lunar_data_2y(symbol: str) -> Optional[pd.DataFrame]:
    """
    Récupère ~2 ans de données via deux appels (2 x 365 jours).
    On spécifie 'start' et 'end' en timestamps (secondes).
    On concatène les DataFrames.
    """

    # "end_date" = maintenant UTC
    end_date = datetime.utcnow()
    # On fera 2 segments (chaque segment = 1 an ~ 365 jours)
    dfs = []

    for _ in range(2):
        start_date = end_date - timedelta(days=365)
        # Conversion en timestamp (secondes)
        end_ts = int(end_date.timestamp())
        start_ts = int(start_date.timestamp())

        url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
        params = {
            "key": LUNAR_API_KEY,
            "bucket": "day",
            "interval": "1y",    # Cf. doc
            "start": start_ts,   # en secondes
            "end": end_ts        # en secondes
        }

        try:
            r = requests.get(url, params=params, timeout=30)
            logging.info(f"[LUNAR 2Y] {symbol} => HTTP {r.status_code} (start={start_ts}, end={end_ts})")
            if r.status_code != 200:
                logging.warning(f"[WARN] {symbol} => code={r.status_code}, skip segment.")
            else:
                j = r.json()
                if "data" in j and j["data"]:
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
                            dt_utc, o, c, h, lo, vol_24, mc, gal, alt_, senti
                        ])

                    if rows:
                        df_tmp = pd.DataFrame(
                            rows,
                            columns=["date","open","close","high","low","volume","market_cap",
                                     "galaxy_score","alt_rank","sentiment"]
                        )
                        dfs.append(df_tmp)
                else:
                    logging.warning(f"[WARN] {symbol} => segment data vide => skip.")
        except Exception as e:
            logging.error(f"[ERROR] {symbol} => {e}")

        # On décale "end_date" d'un an pour la boucle suivante
        end_date = start_date

    # Si rien récupéré
    if not dfs:
        return None

    # Concatène les 2 segments, trie par date, supprime doublons
    df_out = pd.concat(dfs, ignore_index=True)
    df_out.sort_values("date", inplace=True)
    df_out.drop_duplicates(subset=["date"], keep="first", inplace=True)
    df_out.reset_index(drop=True, inplace=True)

    return df_out


########################################
# FONCTIONS UTILES (IDENTIQUES)
########################################

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

########################################
# MAIN
########################################

def main():
    logging.info("=== build_csv (2 ans) => Start ===")

    # 1) Récup data BTC (2 ans) + daily change
    df_btc = fetch_lunar_data_2y("BTC")
    if df_btc is not None and not df_btc.empty:
        df_btc = compute_daily_change(df_btc, "btc_daily_change")
        df_btc = df_btc[["date","btc_daily_change"]]
    else:
        df_btc = pd.DataFrame(columns=["date","btc_daily_change"])

    # 2) Récup data ETH (2 ans) + daily change
    df_eth = fetch_lunar_data_2y("ETH")
    if df_eth is not None and not df_eth.empty:
        df_eth = compute_daily_change(df_eth, "eth_daily_change")
        df_eth = df_eth[["date","eth_daily_change"]]
    else:
        df_eth = pd.DataFrame(columns=["date","eth_daily_change"])

    # 3) Récup data SOL (2 ans) + daily change
    df_sol = fetch_lunar_data_2y("SOL")
    if df_sol is not None and not df_sol.empty:
        df_sol = compute_daily_change(df_sol, "sol_daily_change")
        df_sol = df_sol[["date","sol_daily_change"]]
    else:
        df_sol = pd.DataFrame(columns=["date","sol_daily_change"])

    # 4) Boucle sur altcoins
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

        # Ajout du label (5% sur 2 jours)
        df_alt = compute_label(df_alt, SHIFT_DAYS, THRESHOLD)

        # RSI, MACD, ATR
        df_ind = compute_rsi_macd_atr(df_alt)

        # Copie du label
        df_ind["label"] = df_alt["label"]
        df_ind.dropna(subset=["label"], inplace=True)

        # Ajout 'symbol'
        df_ind["symbol"] = sym

        # Merge BTC
        merged = pd.merge(df_ind, df_btc, on="date", how="left")
        # Merge ETH
        merged = pd.merge(merged, df_eth, on="date", how="left")
        # Merge SOL
        merged = pd.merge(merged, df_sol, on="date", how="left")

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
            "btc_daily_change","eth_daily_change","sol_daily_change"
        ]
        df_empty = pd.DataFrame(columns=columns)
        df_empty.to_csv(OUTPUT_CSV, index=False)
        print(f"[WARN] No data => minimal CSV => {OUTPUT_CSV}")
        return

    # 5) Concat final
    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final.sort_values(["symbol","date"], inplace=True)
    df_final.reset_index(drop=True, inplace=True)

    # Retrait de 'variation', 'future_close' si présents
    for col in ["variation","future_close"]:
        if col in df_final.columns:
            df_final.drop(columns=[col], inplace=True)

    # 6) Export CSV
    df_final.to_csv(OUTPUT_CSV, index=False)
    logging.info(f"Export => {OUTPUT_CSV} => {len(df_final)} rows")
    print(f"Export => {OUTPUT_CSV} ({len(df_final)} rows)")

    logging.info("=== DONE build_csv (2 ans) ===")


if __name__ == "__main__":
    main()