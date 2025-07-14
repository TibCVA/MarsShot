#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_fetcher.py  – LIVE   (compatible modèle v9 : ensemble_mixcalib.pkl)

• Construit daily_inference_data.csv contenant **toutes** les colonnes
  attendues par le modèle entraîné.
• Zéro changement d’interface : les chemins, les clés yaml, les logs
  demeurent identiques aux scripts précédents.
• Concordance stricte avec build_csv_v4_final_tuning.py   (training)
  et backtest_data_builder_90d.py (back‑test).
"""

# ------------------------------------------------------------------ #
# Imports                                                            #
# ------------------------------------------------------------------ #
from __future__ import annotations
import os, sys, argparse, logging, time, requests, yaml, warnings
from datetime import datetime, timedelta, timezone
from typing import Optional, List

import numpy as np
import pandas as pd
import ta
from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException, BinanceRequestException

from indicators import compute_indicators_extended   # même module que training

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ------------------------------------------------------------------ #
# Logging                                                            #
# ------------------------------------------------------------------ #
LOG_FILE = "data_fetcher.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    filemode="a",
    format="%(asctime)s [%(levelname)s] %(message)s",
)
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logging.getLogger().addHandler(console)
log = logging.getLogger(__name__)
log.info("=== START data_fetcher.py – build daily_inference_data.csv ===")

# ------------------------------------------------------------------ #
# Arguments & configuration                                          #
# ------------------------------------------------------------------ #
parser = argparse.ArgumentParser("Data Fetcher for live inference (model v9)")
parser.add_argument("--config", default="", help="Path to config YAML")
args = parser.parse_args()

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = args.config or os.path.join(CUR_DIR, "..", "config.yaml")
OUTPUT_CSV  = os.path.join(CUR_DIR, "..", "daily_inference_data.csv")

if not os.path.exists(CONFIG_FILE):
    log.error("Config %s introuvable – arrêt.", CONFIG_FILE)
    sys.exit(1)

with open(CONFIG_FILE, "r") as fp:
    CFG = yaml.safe_load(fp) or {}

TOKENS_DAILY: List[str] = CFG.get("extended_tokens_daily") \
    or CFG.get("tokens_daily") or []
if not TOKENS_DAILY:
    log.warning("Liste TOKENS_DAILY vide – CSV vide exporté.")
    pd.DataFrame().to_csv(OUTPUT_CSV, index=False)
    sys.exit(0)

LUNAR_API_KEY = CFG.get("lunarcrush", {}).get("api_key", "")
BINANCE_KEY   = CFG.get("binance_api", {}).get("api_key", "")
BINANCE_SEC   = CFG.get("binance_api", {}).get("api_secret", "")

LOOKBACK_DAYS        = 365          # identique au training
SLEEP_BETWEEN_TOKENS = 2.0          # s
MAX_RETRY            = 3
TIMEOUT_S            = 25

# ------------------------------------------------------------------ #
# Binance client (simple sanity‑check de prix)                       #
# ------------------------------------------------------------------ #
binance_client = BinanceClient(BINANCE_KEY, BINANCE_SEC)

# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #
def calculate_slope(s: pd.Series, window: int = 5) -> pd.Series:
    """Pente linéaire (polyfit) sur fenêtre glissante – idem training."""
    out = np.full(len(s), np.nan)
    if len(s) < window:
        return pd.Series(out, index=s.index)
    x = np.arange(window, dtype=float)
    v = s.to_numpy(dtype=float, copy=True)
    for i in range(len(v) - window + 1):
        y = v[i:i + window]
        mask = np.isfinite(y)
        if mask.sum() >= 2:
            out[i + window - 1] = np.polyfit(x[mask], y[mask], 1)[0]
    return pd.Series(out, index=s.index)

# ----------------------- LunarCrush fetch -------------------------- #
LUNAR_URL = "https://lunarcrush.com/api4/public/coins/{sym}/time-series/v2"

def fetch_lunar(sym: str, days: int = 365) -> Optional[pd.DataFrame]:
    """Récupération daily UTC 0h → 0h, max <days> jours, NaN conservés."""
    if not LUNAR_API_KEY:
        return None
    end = datetime.now(timezone.utc).replace(hour=0, minute=0,
                                             second=0, microsecond=0)
    start = end - timedelta(days=days - 1)
    params = dict(key=LUNAR_API_KEY, bucket="day",
                  start=int(start.timestamp()), end=int(end.timestamp()))
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = requests.get(LUNAR_URL.format(sym=sym), params=params,
                             timeout=TIMEOUT_S)
            if r.status_code == 200:
                data = r.json().get("data", [])
                if not data:
                    return None
                rows = [[
                    datetime.utcfromtimestamp(pt["time"]).replace(
                        hour=0, minute=0, second=0, microsecond=0),
                    pt.get("open"), pt.get("close"), pt.get("high"), pt.get("low"),
                    pt.get("volume_24h"), pt.get("market_cap"), pt.get("galaxy_score"),
                    pt.get("alt_rank"), pt.get("sentiment"),
                    pt.get("social_dominance"), pt.get("market_dominance")
                ] for pt in data]
                df = pd.DataFrame(rows, columns=[
                    "date", "open", "close", "high", "low", "volume",
                    "market_cap", "galaxy_score", "alt_rank", "sentiment",
                    "social_dominance", "market_dominance"
                ])
                df.drop_duplicates("date", inplace=True)
                df.sort_values("date", inplace=True, ignore_index=True)
                return df
            if r.status_code in {429, 500, 502, 503, 504}:
                time.sleep(10 * attempt)
        except requests.exceptions.RequestException as exc:
            log.warning("[%s] attempt %d: %s", sym, attempt, exc)
            time.sleep(8 * attempt)
    return None

def verify_price(sym: str, lunar_last_close: float, tolerance: float = .2) -> bool:
    """Compare close LunarCrush (USD) vs Binance‑USDC spot (±tolerance)."""
    try:
        ticker = binance_client.get_symbol_ticker(symbol=f"{sym.upper()}USDC")
        px_binance = float(ticker.get("price", 0))
    except (BinanceAPIException, BinanceRequestException, ValueError):
        return False
    if px_binance == 0:
        return False
    return abs(px_binance - lunar_last_close) / px_binance <= tolerance

# ------------------------------ Benchmarks BTC / ETH --------------- #
def prep_bench(df: pd.DataFrame, pfx: str) -> pd.DataFrame:
    """Reproduit bench_feats() de build_csv.py + compléments back‑test."""
    df = df.copy()
    num_cols = ["open", "high", "low", "close", "volume"]
    df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")
    out = pd.DataFrame({
        "date": df["date"],
        f"{pfx}_close"         : df["close"],
        f"{pfx}_daily_change"  : df["close"].pct_change(1),
        f"{pfx}_3d_change"     : df["close"].pct_change(3),
        f"{pfx}_volume_norm_ma20": df["volume"] / df["volume"].rolling(20).mean()
    })
    atr = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"],
                                         close=df["close"], window=14) \
            .average_true_range()
    rsi = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi()
    out[f"{pfx}_atr_norm"]      = atr / df["close"].replace(0, np.nan)
    out[f"{pfx}_rsi"]           = rsi
    out[f"{pfx}_price_std_7d"]  = df["close"].rolling(7).std()
    out[f"{pfx}_price_std_30d"] = df["close"].rolling(30).std() / df["close"]
    return out

log.info("Téléchargement BTC / ETH benchmarks…")
btc_raw = fetch_lunar("BTC", LOOKBACK_DAYS + 60)
eth_raw = fetch_lunar("ETH", LOOKBACK_DAYS + 60)
if btc_raw is None or eth_raw is None:
    log.critical("Impossible de récupérer BTC ou ETH – arrêt.")
    sys.exit(1)
btc_bench = prep_bench(btc_raw, "btc")
eth_bench = prep_bench(eth_raw, "eth")

# ------------------------------------------------------------------ #
# Boucle principale Tokens                                           #
# ------------------------------------------------------------------ #
numeric_base_cols = ["open","high","low","close","volume","market_cap",
                     "galaxy_score","alt_rank","sentiment",
                     "social_dominance","market_dominance"]

dfs_tokens: List[pd.DataFrame] = []
n_tot = len(TOKENS_DAILY)
log.info("Traitement %d tokens…", n_tot)

for idx, sym in enumerate(TOKENS_DAILY, 1):
    log.info("[%d/%d] %s", idx, n_tot, sym)
    raw = fetch_lunar(sym, LOOKBACK_DAYS)
    if raw is None or len(raw) < 60:
        log.warning("[%s] données insuffisantes – skip", sym)
        continue

    # --- Validation prix vs Binance (optionnelle mais prudente) ----
    last_close = pd.to_numeric(raw["close"], errors="coerce").dropna().iloc[-1]
    if not verify_price(sym, last_close):
        log.warning("[%s] écart prix Binance > 20 %% – skip", sym)
        continue

    # -------------------------------------------------------------- #
    # Préparation & indicateurs techniques identiques au training    #
    # -------------------------------------------------------------- #
    df = raw.copy()
    df[numeric_base_cols] = df[numeric_base_cols] \
        .apply(pd.to_numeric, errors="coerce")
    df["volume"].fillna(0.0, inplace=True)

    df_feat = compute_indicators_extended(df)
    df_feat.set_index("date", inplace=True)

    # ------------- Features étendues ------------------------------ #
    df_feat["atr14_norm"]              = df_feat["atr14"] / df_feat["close"].replace(0, np.nan)
    df_feat["price_change_norm_atr1d"] = df_feat["close"].diff() / df_feat["atr14"].shift()
    df_feat["rsi14_roc3d"]             = df_feat["rsi14"].diff(3)
    df_feat["ma_slope_7d"]             = calculate_slope(df_feat["ma_close_7d"])
    df_feat["ma_slope_14d"]            = calculate_slope(df_feat["ma_close_14d"])

    bb = ta.volatility.BollingerBands(df_feat["close"], window=20, window_dev=2)
    mavg = bb.bollinger_mavg().replace(0, np.nan)
    df_feat["boll_width_norm"] = (bb.bollinger_hband() - bb.bollinger_lband()) / mavg

    df_feat["volume_norm_ma20"]       = df_feat["volume"] / df_feat["volume"].rolling(20).mean()
    df_feat["galaxy_score_norm_ma7"]  = df_feat["galaxy_score"] / df_feat["galaxy_score"].rolling(7).mean()
    df_feat["sentiment_ma_diff7"]     = df_feat["sentiment"] - df_feat["sentiment"].rolling(7).mean()
    df_feat["alt_rank_roc1d"]         = df_feat["alt_rank"].diff()
    df_feat["alt_rank_roc7d"]         = df_feat["alt_rank"].diff(7)
    df_feat["obv_slope_5d"]           = calculate_slope(df_feat["obv"])

    # ---- Deltas --------------------------------------------------- #
    df_feat["delta_close_1d"] = df_feat["close"].pct_change(1)
    df_feat["delta_close_3d"] = df_feat["close"].pct_change(3)
    df_feat["delta_vol_1d"]   = df_feat["volume"].pct_change(1)
    df_feat["delta_vol_3d"]   = df_feat["volume"].pct_change(3)
    df_feat["delta_mcap_1d"]  = df_feat["market_cap"].pct_change(1)
    df_feat["delta_mcap_3d"]  = df_feat["market_cap"].pct_change(3)

    df_feat["delta_galaxy_1d"]      = df_feat["galaxy_score"].diff(1)
    df_feat["delta_galaxy_3d"]      = df_feat["galaxy_score"].diff(3)
    df_feat["delta_social_dom_1d"]  = df_feat["social_dominance"].diff(1)
    df_feat["delta_social_dom_3d"]  = df_feat["social_dominance"].diff(3)
    df_feat["delta_market_dom_1d"]  = df_feat["market_dominance"].diff(1)
    df_feat["delta_market_dom_3d"]  = df_feat["market_dominance"].diff(3)
    df_feat["delta_alt_rank_3d"]    = df_feat["alt_rank"].diff(3)  # pas de 1d au training

    df_feat.reset_index(inplace=True)  # facilite les merges

    # ---- Fusion BTC / ETH ---------------------------------------- #
    merged = (df_feat.merge(btc_bench, on="date", how="left")
                       .merge(eth_bench, on="date", how="left"))

    merged["rsi_vs_btc"]      = merged["rsi14"]     - merged["btc_rsi"]
    merged["atr_norm_vs_btc"] = merged["atr14_norm"] - merged["btc_atr_norm"]

    avg_atr = (merged["btc_atr_norm"].fillna(0) + merged["eth_atr_norm"].fillna(0)) / 2
    merged["volatility_ratio_vs_market"] = merged["atr14_norm"] / avg_atr.replace(0, np.nan)

    # ---- Temporal features & metadata ---------------------------- #
    merged["dow"]   = merged["date"].dt.dayofweek.astype("int8")
    merged["dom"]   = merged["date"].dt.day.astype("int8")
    merged["month"] = merged["date"].dt.month.astype("int8")
    merged["symbol"] = sym

    merged.replace([np.inf, -np.inf], np.nan, inplace=True)
    dfs_tokens.append(merged)
    time.sleep(SLEEP_BETWEEN_TOKENS)

# ------------------------------------------------------------------ #
# Export                                                             #
# ------------------------------------------------------------------ #
if not dfs_tokens:
    log.warning("Aucun token retenu – export CSV vide.")
    pd.DataFrame().to_csv(OUTPUT_CSV, index=False)
    sys.exit(0)

df_all = pd.concat(dfs_tokens, ignore_index=True)
df_all.sort_values(["symbol", "date"], inplace=True)
df_all.reset_index(drop=True, inplace=True)

df_all.to_csv(OUTPUT_CSV, index=False)
log.info("✅ daily_inference_data.csv écrit (%d lignes, %d colonnes)",
         len(df_all), len(df_all.columns))
print(f"[OK] => {OUTPUT_CSV} ({len(df_all)} rows, {len(df_all.columns)} cols)")
