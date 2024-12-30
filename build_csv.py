#!/usr/bin/env python3
# coding: utf-8

import requests
import pandas as pd
import time
import logging
import os
from datetime import datetime, timedelta

#####################################
# PARAMÈTRES GLOBAUX ET CLÉS API
#####################################
CMC_API_KEY = "0a602f8f-2a68-4992-89f2-7e7416a4d8e8"
LUNAR_API_KEY = "85zhfo9yl9co22cl7kw2sucossm59awchvwf8s8ub"

DAYS = 30                  # Nombre de jours d’historique prix
SHIFT_DAYS = 2             # Décalage pour calcul du label
THRESHOLD = 0.30           # Seuil de hausse pour label = 1
OUTPUT_CSV = "training_data.csv"
LOG_FILE = "build_csv.log"

# Configuration du logger
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START build_csv ===")

#####################################
# LISTE DES TOKENS (102)
# (Même structure qu'avant, mais on retire nansen/holders)
#####################################
TOKENS = [
    {
        "symbol": "SOLVEX",
        "cmc_id": 9604,
        "lunar_symbol": "SOLVEX"
    },
    {
        "symbol": "PATRIOT",
        "cmc_id": 2988,
        "lunar_symbol": "PATRIOT"
    },
    {
        "symbol": "FAI",
        "cmc_id": 28885,
        "lunar_symbol": "FAI"
    },
    {
        "symbol": "MOEW",
        "cmc_id": 28839,
        "lunar_symbol": "MOEW"
    },
    {
        "symbol": "A8",
        "cmc_id": 28136,
        "lunar_symbol": "A8"
    },
    {
        "symbol": "GNON",
        "cmc_id": 28477,
        "lunar_symbol": "GNON"
    },
    {
        "symbol": "COOKIE",
        "cmc_id": 28991,
        "lunar_symbol": "COOKIE"
    },
    {
        "symbol": "LOFI",
        "cmc_id": 27987,
        "lunar_symbol": "LOFI"
    },
    {
        "symbol": "PRQ",
        "cmc_id": 7208,
        "lunar_symbol": "PRQ"
    },
    {
        "symbol": "CHAMP",
        "cmc_id": 28344,
        "lunar_symbol": "CHAMP"
    },
    {
        "symbol": "PHA",
        "cmc_id": 6841,
        "lunar_symbol": "PHA"
    },
    {
        "symbol": "UXLINK",
        "cmc_id": 28810,
        "lunar_symbol": "UXLINK"
    },
    {
        "symbol": "KOMA",
        "cmc_id": 28356,
        "lunar_symbol": "KOMA"
    },
    {
        "symbol": "COW",
        "cmc_id": 11042,
        "lunar_symbol": "COW"
    },
    {
        "symbol": "MORPHO",
        "cmc_id": 27950,
        "lunar_symbol": "MORPHO"
    },
    {
        "symbol": "WILD",
        "cmc_id": 9674,
        "lunar_symbol": "WILD"
    },
    {
        "symbol": "MCADE",
        "cmc_id": 24660,
        "lunar_symbol": "MCADE"
    },
    {
        "symbol": "AIXBT",
        "cmc_id": 28743,
        "lunar_symbol": "AIXBT"
    },
    {
        "symbol": "NETVR",
        "cmc_id": 28770,
        "lunar_symbol": "NETVR"
    },
    {
        "symbol": "XVG",
        "cmc_id": 693,
        "lunar_symbol": "XVG"
    },
    {
        "symbol": "AVA",
        "cmc_id": 4646,
        "lunar_symbol": "AVA"
    },
    {
        "symbol": "XYO",
        "cmc_id": 2765,
        "lunar_symbol": "XYO"
    },
    {
        "symbol": "WHBAR",
        "cmc_id": 28571,
        "lunar_symbol": "WHBAR"
    },
    {
        "symbol": "PAAL",
        "cmc_id": 28729,
        "lunar_symbol": "PAAL"
    },
    {
        "symbol": "OL",
        "cmc_id": 28897,
        "lunar_symbol": "OL"
    },
    {
        "symbol": "LKI",
        "cmc_id": 28634,
        "lunar_symbol": "LKI"
    },
    {
        "symbol": "APX",
        "cmc_id": 21792,
        "lunar_symbol": "APX"
    },
    {
        "symbol": "DF",
        "cmc_id": 5777,
        "lunar_symbol": "DF"
    },
    {
        "symbol": "EL",
        "cmc_id": 7505,
        "lunar_symbol": "EL"
    },
    {
        "symbol": "VELO",
        "cmc_id": 20461,
        "lunar_symbol": "VELO"
    },
    {
        "symbol": "SRX",
        "cmc_id": 10798,
        "lunar_symbol": "SRX"
    },
    {
        "symbol": "ACX",
        "cmc_id": 19163,
        "lunar_symbol": "ACX"
    },
    {
        "symbol": "COMAI",
        "cmc_id": 28649,
        "lunar_symbol": "COMAI"
    },
    {
        "symbol": "ZENT",
        "cmc_id": 28552,
        "lunar_symbol": "ZENT"
    },
    {
        "symbol": "WOLF",
        "cmc_id": 28901,
        "lunar_symbol": "WOLF"
    },
    {
        "symbol": "ZEN",
        "cmc_id": 1698,
        "lunar_symbol": "ZEN"
    },
    {
        "symbol": "GEAR",
        "cmc_id": 28352,
        "lunar_symbol": "GEAR"
    },
    {
        "symbol": "TOMI",
        "cmc_id": 16834,
        "lunar_symbol": "TOMI"
    },
    {
        "symbol": "ARTY",
        "cmc_id": 28789,
        "lunar_symbol": "ARTY"
    },
    {
        "symbol": "URO",
        "cmc_id": 28899,
        "lunar_symbol": "URO"
    },
    {
        "symbol": "AXOL",
        "cmc_id": 28547,
        "lunar_symbol": "AXOL"
    },
    {
        "symbol": "AAAHHM",
        "cmc_id": 28876,
        "lunar_symbol": "AAAHHM"
    },
    {
        "symbol": "ATA",
        "cmc_id": 10188,
        "lunar_symbol": "ATA"
    },
    {
        "symbol": "UTK",
        "cmc_id": 28816,
        "lunar_symbol": "UTK"
    },
    {
        "symbol": "PEAQ",
        "cmc_id": 22766,
        "lunar_symbol": "PEAQ"
    },
    {
        "symbol": "CELL",
        "cmc_id": 8993,
        "lunar_symbol": "CELL"
    },
    {
        "symbol": "IDEX",
        "cmc_id": 3928,
        "lunar_symbol": "IDEX"
    },
    {
        "symbol": "PUFFER",
        "cmc_id": 28522,
        "lunar_symbol": "PUFFER"
    },
    {
        "symbol": "CA",
        "cmc_id": 28713,
        "lunar_symbol": "CA"
    },
    {
        "symbol": "ORDER",
        "cmc_id": 27682,
        "lunar_symbol": "ORDER"
    },
    {
        "symbol": "CXT",
        "cmc_id": 28635,
        "lunar_symbol": "CXT"
    },
    {
        "symbol": "TERMINUS",
        "cmc_id": 28874,
        "lunar_symbol": "TERMINUS"
    },
    {
        "symbol": "SYNT",
        "cmc_id": 28453,
        "lunar_symbol": "SYNT"
    },
    {
        "symbol": "ZKJ",
        "cmc_id": 28237,
        "lunar_symbol": "ZKJ"
    },
    {
        "symbol": "DBR",
        "cmc_id": 28246,
        "lunar_symbol": "DBR"
    },
    {
        "symbol": "FORTH",
        "cmc_id": 9421,
        "lunar_symbol": "FORTH"
    },
    {
        "symbol": "FIRO",
        "cmc_id": 1414,
        "lunar_symbol": "FIRO"
    },
    {
        "symbol": "RNDR",
        "cmc_id": 5690,
        "lunar_symbol": "RNDR"
    },
    {
        "symbol": "INJ",
        "cmc_id": 7226,
        "lunar_symbol": "INJ"
    },
    {
        "symbol": "GRT",
        "cmc_id": 6719,
        "lunar_symbol": "GRT"
    },
    {
        "symbol": "RLC",
        "cmc_id": 1637,
        "lunar_symbol": "RLC"
    },
    {
        "symbol": "OCEAN",
        "cmc_id": 3911,
        "lunar_symbol": "OCEAN"
    },
    {
        "symbol": "AGIX",
        "cmc_id": 2424,
        "lunar_symbol": "AGIX"
    },
    {
        "symbol": "FET",
        "cmc_id": 3773,
        "lunar_symbol": "FET"
    },
    {
        "symbol": "ROSE",
        "cmc_id": 7653,
        "lunar_symbol": "ROSE"
    },
    {
        "symbol": "CTSI",
        "cmc_id": 5444,
        "lunar_symbol": "CTSI"
    },
    {
        "symbol": "CQT",
        "cmc_id": 9467,
        "lunar_symbol": "CQT"
    },
    {
        "symbol": "DAG",
        "cmc_id": 3843,
        "lunar_symbol": "DAG"
    },
    {
        "symbol": "UOS",
        "cmc_id": 4184,
        "lunar_symbol": "UOS"
    },
    {
        "symbol": "PYR",
        "cmc_id": 8750,
        "lunar_symbol": "PYR"
    },
    {
        "symbol": "ILV",
        "cmc_id": 9399,
        "lunar_symbol": "ILV"
    },
    {
        "symbol": "AXS",
        "cmc_id": 6783,
        "lunar_symbol": "AXS"
    },
    {
        "symbol": "SAND",
        "cmc_id": 6210,
        "lunar_symbol": "SAND"
    },
    {
        "symbol": "MANA",
        "cmc_id": 1966,
        "lunar_symbol": "MANA"
    },
    {
        "symbol": "ENJ",
        "cmc_id": 2130,
        "lunar_symbol": "ENJ"
    },
    {
        "symbol": "GALA",
        "cmc_id": 7080,
        "lunar_symbol": "GALA"
    },
    {
        "symbol": "ALICE",
        "cmc_id": 8766,
        "lunar_symbol": "ALICE"
    },
    # Ajout 78 → 102
    {
        "symbol": "APT",
        "cmc_id": 21794,
        "lunar_symbol": "APT"
    },
    {
        "symbol": "OP",
        "cmc_id": 11840,
        "lunar_symbol": "OP"
    },
    {
        "symbol": "ARB",
        "cmc_id": 11841,
        "lunar_symbol": "ARB"
    },
    {
        "symbol": "FTM",
        "cmc_id": 3513,
        "lunar_symbol": "FTM"
    },
    {
        "symbol": "NEAR",
        "cmc_id": 6535,
        "lunar_symbol": "NEAR"
    },
    {
        "symbol": "AAVE",
        "cmc_id": 7278,
        "lunar_symbol": "AAVE"
    },
    {
        "symbol": "XTZ",
        "cmc_id": 2011,
        "lunar_symbol": "XTZ"
    },
    {
        "symbol": "THETA",
        "cmc_id": 2416,
        "lunar_symbol": "THETA"
    },
    {
        "symbol": "FLOW",
        "cmc_id": 4558,
        "lunar_symbol": "FLOW"
    },
    {
        "symbol": "EGLD",
        "cmc_id": 6892,
        "lunar_symbol": "EGLD"
    },
    {
        "symbol": "ICP",
        "cmc_id": 8916,
        "lunar_symbol": "ICP"
    },
    {
        "symbol": "VET",
        "cmc_id": 3077,
        "lunar_symbol": "VET"
    },
    {
        "symbol": "HBAR",
        "cmc_id": 4642,
        "lunar_symbol": "HBAR"
    },
    {
        "symbol": "ALGO",
        "cmc_id": 4030,
        "lunar_symbol": "ALGO"
    },
    {
        "symbol": "STX",
        "cmc_id": 4847,
        "lunar_symbol": "STX"
    },
    {
        "symbol": "EOS",
        "cmc_id": 1765,
        "lunar_symbol": "EOS"
    },
    {
        "symbol": "KAVA",
        "cmc_id": 4846,
        "lunar_symbol": "KAVA"
    },
    {
        "symbol": "ZIL",
        "cmc_id": 2469,
        "lunar_symbol": "ZIL"
    },
    {
        "symbol": "1INCH",
        "cmc_id": 8104,
        "lunar_symbol": "1INCH"
    },
    {
        "symbol": "GNO",
        "cmc_id": 1659,
        "lunar_symbol": "GNO"
    },
    {
        "symbol": "LRC",
        "cmc_id": 1934,
        "lunar_symbol": "LRC"
    },
    {
        "symbol": "SUSHI",
        "cmc_id": 6758,
        "lunar_symbol": "SUSHI"
    },
    {
        "symbol": "BAL",
        "cmc_id": 6538,
        "lunar_symbol": "BAL"
    },
    {
        "symbol": "YFI",
        "cmc_id": 5864,
        "lunar_symbol": "YFI"
    },
    {
        "symbol": "SRM",
        "cmc_id": 6187,
        "lunar_symbol": "SRM"
    },
]

#####################################
# FONCTIONS
#####################################

# Compteur global pour coinmarketcap => pause après 30 appels
CMC_CALL_COUNT = 0

def fetch_cmc_history(cmc_id, days=30):
    """
    Récupère l'historique daily sur 'days' jours pour le token (id=cmc_id).
    Retourne un DataFrame [date, close, volume, market_cap].
    Si échec => retourne None.
    """
    global CMC_CALL_COUNT

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
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

    # Pause si on atteint un multiple de 30
    CMC_CALL_COUNT += 1
    if CMC_CALL_COUNT % 30 == 0:
        logging.info("[CMC DEBUG] Reached 30 calls => sleeping 60s to avoid 429")
        time.sleep(60)

    try:
        r = requests.get(url, headers=headers, params=params, timeout=25)
        logging.info(f"[CMC DEBUG] cmc_id={cmc_id} status_code={r.status_code}")
        if r.status_code != 200:
            logging.warning(f"[CMC WARNING] cmc_id={cmc_id}, HTTP={r.status_code} => skip.")
            return None

        j = r.json()
        if "data" not in j or not j["data"]:
            return None

        quotes = j["data"].get("quotes", [])
        if not quotes:
            return None

        rows = []
        for q in quotes:
            t = q.get("timestamp")
            if not t:
                continue
            dd = datetime.fromisoformat(t.replace("Z",""))
            usd = q["quote"].get("USD", {})
            c = usd.get("close")
            vol = usd.get("volume")
            mc = usd.get("market_cap")

            # On peut récupérer open, high, low si on veut, mais on se concentre sur close/volume/market_cap
            if c is None:
                continue
            rows.append([dd, c, vol, mc])

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=["date","close","volume","market_cap"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    except Exception as e:
        logging.error(f"[CMC ERROR] {cmc_id} => {e}")
        return None


def fetch_lunar_time_series(symbol, days=30):
    """
    Récupère l'historique daily (bucket=day, interval=1m => ~30 jours)
    On y lit galaxy_score, alt_rank, sentiment. On renvoie un DataFrame
    [date, galaxy_score, alt_rank, sentiment].
    Si échec => renvoie DataFrame vide (on mettra des valeurs par défaut après).
    """
    # On utilise la doc : GET /api4/public/coins/<symbol>/time-series/v2
    # bucket=day, interval=1m
    # On attend ~ 30 derniers jours. L'API n'a pas de param `days` exact,
    # l'interval=1m => ~30 jours.

    base_url = f"https://lunarcrush.com/api4/public/coins/{symbol}/time-series/v2"
    params = {
        "key": LUNAR_API_KEY,
        "bucket": "day",
        "interval": "1m"
    }

    # On peut rajouter un retry si besoin, ici on fait simple
    try:
        r = requests.get(base_url, params=params, timeout=25)
        if r.status_code != 200:
            logging.warning(f"[LUNAR WARNING] {symbol} => HTTP={r.status_code} => empty df.")
            return pd.DataFrame()

        j = r.json()
        if "data" not in j or not j["data"]:
            logging.warning(f"[LUNAR WARNING] {symbol} => no data => empty df.")
            return pd.DataFrame()

        rows = []
        for point in j["data"]:
            # time est un int epoch
            epoch_ts = point.get("time")
            if epoch_ts is None:
                continue
            dt_utc = datetime.utcfromtimestamp(epoch_ts)

            galaxy = point.get("galaxy_score", None)
            alt_r = point.get("alt_rank", None)
            senti = point.get("sentiment", None)

            rows.append([dt_utc, galaxy, alt_r, senti])

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["date","galaxy_score","alt_rank","sentiment"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    except Exception as e:
        logging.error(f"[LUNAR ERROR] {symbol} => {e}")
        return pd.DataFrame()


def compute_label(df):
    """
    Sur df déjà trié par date, on calcule label binaire :
    SHIFT_DAYS=2 => on compare close d'aujourd'hui vs close dans 2 jours
    label=1 si +30% (THRESHOLD=0.3), sinon 0
    """
    df = df.sort_values("date").reset_index(drop=True)
    df["price_future"] = df["close"].shift(-SHIFT_DAYS)
    df["variation_2d"] = (df["price_future"] - df["close"]) / df["close"]
    df["label"] = (df["variation_2d"] >= THRESHOLD).astype(int)
    return df


def main():
    logging.info("=== build_csv => collecting data for 102 tokens (no Nansen, advanced Lunar) ===")
    all_dfs = []

    for i, t in enumerate(TOKENS):
        sym = t["symbol"]
        cmc_id = t["cmc_id"]
        lunar_sym = t["lunar_symbol"]

        logging.info(f"... fetching CMC for {sym} (id={cmc_id})")
        df_cmc = fetch_cmc_history(cmc_id, DAYS)
        if df_cmc is None or df_cmc.empty:
            logging.warning(f"No data from CMC => skip token {sym}")
            continue

        logging.info(f"... fetching LunarCrush time-series for {sym} -> {lunar_sym}")
        df_lunar = fetch_lunar_time_series(lunar_sym, DAYS)
        # si c'est vide => on forcera des valeurs par défaut
        if df_lunar.empty:
            logging.warning(f"No lunar data => will fill default for {sym}")
            # On fabrique un df_lunar 'bidon' avec juste les dates du df_cmc
            # et galaxy_score=0, alt_rank=999999, sentiment=0.5
            df_lunar = df_cmc[["date"]].copy()
            df_lunar["galaxy_score"] = 0
            df_lunar["alt_rank"] = 999999
            df_lunar["sentiment"] = 0.5
        else:
            # On veut un merge sur la date (jour) : 
            # orientez-vous sur la même granularité
            # Les dates CMC sont surement hh:mm:ss, idem lunar => on merge sur date arrondie ?
            # Approche simple => on fait la "date" -> date() pour un join sur le jour
            df_cmc["day"] = df_cmc["date"].dt.date
            df_lunar["day"] = df_lunar["date"].dt.date

            merged = pd.merge(df_cmc, df_lunar, on="day", how="left", suffixes=("_cmc","_lunar"))

            # On doit reconstituer la date "finale"
            # On garde date_cmc comme date
            merged.rename(columns={"date_cmc": "date"}, inplace=True)

            # On remplace NaN par valeurs par défaut
            merged["galaxy_score"] = merged["galaxy_score"].fillna(0)
            merged["alt_rank"] = merged["alt_rank"].fillna(999999)
            merged["sentiment"] = merged["sentiment"].fillna(0.5)

            # On sélectionne colonnes utiles
            merged = merged.sort_values("date").reset_index(drop=True)
            # On renomme "close" "volume" "market_cap" => c'est dans merged ?
            # close => close, volume => volume, market_cap => market_cap
            # On supprime les colonnes date_lunar ou ?

            # Conserve : "date","close","volume","market_cap","galaxy_score","alt_rank","sentiment"
            final_cols = ["date","close","volume","market_cap","galaxy_score","alt_rank","sentiment"]
            df_cmc = merged[final_cols].copy()

        # Maintenant df_cmc contient date,close,volume,market_cap,galaxy_score,alt_rank,sentiment
        # On compute label
        df_label = compute_label(df_cmc)
        df_label["token"] = sym  # On ajoute la colonne token

        # On reorder
        columns_order = ["token","date","close","volume","market_cap","galaxy_score","alt_rank","sentiment","label"]
        df_label = df_label[columns_order]

        # on enlève les lignes sans label (les 2 derniers jours)
        df_label.dropna(subset=["label"], inplace=True)

        all_dfs.append(df_label)

        # Un petit sleep(2) pour éviter trop de requêtes Lunar en rafale
        time.sleep(2)

    # On concat
    if not all_dfs:
        logging.warning("No data => no CSV.")
        print("No data => no CSV.")
        return

    df_final = pd.concat(all_dfs, ignore_index=True)
    df_final = df_final.sort_values(["token","date"]).reset_index(drop=True)

    df_final.to_csv(OUTPUT_CSV, index=False)
    nb_rows = len(df_final)
    logging.info(f"Export => {OUTPUT_CSV} => {nb_rows} lignes.")
    print(f"Export => {OUTPUT_CSV} => {nb_rows} lignes.")


if __name__ == "__main__":
    main()
