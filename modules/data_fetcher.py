#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_fetcher.py  – LIVE (modèle v9 : ensemble_mixcalib.pkl)

VERSION
-------
v9.1.0 (2025-12-15)
- Fix critique: évite le crash iloc[-1] quand LunarCrush renvoie une série close vide/non-numérique.
- Robustesse: try/except par token (un token "cassé" ne stoppe plus le job).
- Logs diagnostic enrichis (close vide, colonnes reçues, last_row, raisons de skip).
- Parité backtest conservée:
  - Borne LunarCrush : fin à J-1 23:59:59.999999 UTC (today 00:00 - 1µs)
  - Benchmarks BTC/ETH : 0→NaN puis ffill().bfill() avant calculs
  - Token-level : pas de volume NaN -> 0 (on laisse les NaN)
  - Vérification Binance/USDC (verify_price) conservée telle quelle

OBJECTIF
--------
Construire daily_inference_data.csv contenant toutes les colonnes attendues
par le modèle entraîné (ensemble_mixcalib.pkl), en concordance stricte avec:
- build_csv_v4_final_tuning.py (training)
- backtest_data_builder_90d.py (backtest)
"""

# ------------------------------------------------------------------ #
# Imports                                                            #
# ------------------------------------------------------------------ #
from __future__ import annotations

import os
import sys
import argparse
import logging
import time
import warnings
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple

import numpy as np
import pandas as pd
import requests
import ta
import yaml
from binance.client import Client as BinanceClient

from indicators import compute_indicators_extended  # même module que training

# ------------------------------------------------------------------ #
# Constantes / Version                                               #
# ------------------------------------------------------------------ #
__VERSION__ = "9.1.0"
__BUILD_DATE__ = "2025-12-15"

# ------------------------------------------------------------------ #
# Warnings                                                           #
# ------------------------------------------------------------------ #
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
log.info("Version: v%s (%s) | Python=%s", __VERSION__, __BUILD_DATE__, sys.version.split()[0])

# ------------------------------------------------------------------ #
# Helpers généraux                                                   #
# ------------------------------------------------------------------ #
def calculate_slope(s: pd.Series, window: int = 5) -> pd.Series:
    """Pente linéaire (polyfit) sur fenêtre glissante – idem training."""
    out = np.full(len(s), np.nan)
    if len(s) < window:
        return pd.Series(out, index=s.index)
    x = np.arange(window, dtype=float)
    v = s.to_numpy(dtype=float, copy=True)
    for i in range(len(v) - window + 1):
        y = v[i : i + window]
        mask = np.isfinite(y)
        if mask.sum() >= 2:
            out[i + window - 1] = np.polyfit(x[mask], y[mask], 1)[0]
    return pd.Series(out, index=s.index)


def _safe_numeric_series(df: pd.DataFrame, col: str) -> pd.Series:
    """
    Retourne une Series numérique nettoyée (to_numeric + dropna).
    Ne lève pas si col absente: renvoie Series vide.
    """
    if col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce").dropna()


def _tail_as_dict(df: pd.DataFrame, n: int = 1) -> List[dict]:
    """Aide debug: renvoie les n dernières lignes en dict, sans lever."""
    try:
        if df is None or df.empty:
            return []
        return df.tail(n).to_dict(orient="records")
    except Exception:
        return []


# ------------------------------------------------------------------ #
# LunarCrush fetch                                                   #
# ------------------------------------------------------------------ #
LUNAR_URL = "https://lunarcrush.com/api4/public/coins/{sym}/time-series/v2"

def fetch_lunar(sym: str,
                api_key: str,
                days: int = 365,
                max_retry: int = 3,
                timeout_s: int = 25,
                session: Optional[requests.Session] = None) -> Optional[pd.DataFrame]:
    """
    Récupération daily UTC (bucket 'day'), max <days> jours, NaN conservés.
    Parité backtest : borne de fin = J-1 23:59:59.999999 UTC.
    """
    if not api_key:
        return None

    sess = session or requests.Session()

    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_yest = end - timedelta(microseconds=1)        # J-1 23:59:59.999999 UTC
    start = end_yest - timedelta(days=days - 1)

    params = dict(
        key=api_key,
        bucket="day",
        start=int(start.timestamp()),
        end=int(end_yest.timestamp()),
    )

    for attempt in range(1, max_retry + 1):
        try:
            r = sess.get(
                LUNAR_URL.format(sym=sym),
                params=params,
                timeout=timeout_s,
                headers={"Accept": "application/json"},
            )

            # Cas non récupérables (auth / forbidden)
            if r.status_code in {401, 403}:
                log.error("[%s] LunarCrush HTTP %s (auth/forbidden). Vérifie la clé API.", sym, r.status_code)
                return None

            # Cas OK
            if r.status_code == 200:
                try:
                    payload = r.json()
                except ValueError as exc:
                    log.warning("[%s] JSON invalide LunarCrush (attempt %d/%d): %s", sym, attempt, max_retry, exc)
                    time.sleep(3 * attempt)
                    continue

                data = payload.get("data", [])
                if not data:
                    return None

                rows = []
                for pt in data:
                    # Note: pt["time"] est attendu, mais on sécurise
                    t = pt.get("time")
                    if t is None:
                        continue
                    rows.append([
                        datetime.utcfromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0),
                        pt.get("open"),
                        pt.get("close"),
                        pt.get("high"),
                        pt.get("low"),
                        pt.get("volume_24h"),
                        pt.get("market_cap"),
                        pt.get("galaxy_score"),
                        pt.get("alt_rank"),
                        pt.get("sentiment"),
                        pt.get("social_dominance"),
                        pt.get("market_dominance"),
                    ])

                if not rows:
                    return None

                df = pd.DataFrame(rows, columns=[
                    "date", "open", "close", "high", "low", "volume",
                    "market_cap", "galaxy_score", "alt_rank", "sentiment",
                    "social_dominance", "market_dominance"
                ])
                df.drop_duplicates("date", inplace=True)
                df.sort_values("date", inplace=True, ignore_index=True)
                return df

            # Erreurs temporaires / rate-limit -> backoff
            if r.status_code in {429, 500, 502, 503, 504}:
                wait_s = 10 * attempt
                log.warning("[%s] LunarCrush HTTP %s (attempt %d/%d) -> retry in %ss",
                            sym, r.status_code, attempt, max_retry, wait_s)
                time.sleep(wait_s)
                continue

            # Autres erreurs HTTP -> log et stop pour ce token
            log.warning("[%s] LunarCrush HTTP %s (non-retry). Body=%s",
                        sym, r.status_code, (r.text[:200] if r.text else ""))
            return None

        except requests.exceptions.RequestException as exc:
            wait_s = 8 * attempt
            log.warning("[%s] LunarCrush request error (attempt %d/%d): %s -> retry in %ss",
                        sym, attempt, max_retry, exc, wait_s)
            time.sleep(wait_s)

    return None


# ------------------------------------------------------------------ #
# Binance (sanity-check prix J-1)                                    #
# ------------------------------------------------------------------ #
def _binance_yesterday_close_usdc(client: BinanceClient, sym: str) -> Optional[float]:
    """
    Retourne la clôture DAILY J-1 sur Binance (paire USDC) pour comparer
    à la dernière clôture J-1 LunarCrush.
    On prend la bougie -2 pour éviter la bougie du jour en cours si incluse.
    """
    pair = f"{sym.upper()}USDC"
    try:
        kl = client.get_klines(
            symbol=pair,
            interval=BinanceClient.KLINE_INTERVAL_1DAY,
            limit=2
        )
        if not kl:
            return None
        idx = -2 if len(kl) >= 2 else -1  # dernière bougie *fermée*
        return float(kl[idx][4])          # close
    except Exception:
        return None


def verify_price(client: BinanceClient,
                 sym: str,
                 lunar_last_close: float,
                 tolerance: float = 0.2) -> bool:
    """
    Compare la *dernière clôture J-1* LunarCrush à la *clôture DAILY J-1*
    Binance (paire USDC). Évite de rejeter à tort lors des périodes volatiles.
    """
    try:
        if not np.isfinite(lunar_last_close) or lunar_last_close <= 0:
            return False
    except Exception:
        return False

    y_close = _binance_yesterday_close_usdc(client, sym)
    if not y_close or y_close <= 0:
        return False

    return abs(y_close - lunar_last_close) / y_close <= tolerance


# ------------------------------------------------------------------ #
# Benchmarks BTC / ETH                                               #
# ------------------------------------------------------------------ #
def prep_bench(df: pd.DataFrame, pfx: str) -> pd.DataFrame:
    """
    Parité backtest: 0→NaN puis ffill/bfill avant calculs.
    Colonnes générées : {pfx}_close, {pfx}_daily_change, {pfx}_3d_change,
    {pfx}_volume_norm_ma20, {pfx}_atr_norm, {pfx}_rsi, {pfx}_price_std_7d,
    {pfx}_price_std_30d (std/close).
    """
    df = df.copy()

    # Assure présence colonnes (robuste si API change)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = np.nan

    num_cols = ["open", "high", "low", "close", "volume"]
    df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")

    # parité backtest
    df = df.replace(0, np.nan).ffill().bfill()

    out = pd.DataFrame({
        "date": df["date"],
        f"{pfx}_close": df["close"],
        f"{pfx}_daily_change": df["close"].pct_change(1),
        f"{pfx}_3d_change": df["close"].pct_change(3),
        f"{pfx}_volume_norm_ma20": df["volume"] / df["volume"].rolling(20).mean(),
    })

    atr = ta.volatility.AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()

    rsi = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi()

    out[f"{pfx}_atr_norm"] = atr / df["close"].replace(0, np.nan)
    out[f"{pfx}_rsi"] = rsi
    out[f"{pfx}_price_std_7d"] = df["close"].rolling(7).std()
    out[f"{pfx}_price_std_30d"] = df["close"].rolling(30).std() / df["close"]

    return out


# ------------------------------------------------------------------ #
# MAIN                                                               #
# ------------------------------------------------------------------ #
def main() -> int:
    # -------------------- Args & config --------------------------- #
    parser = argparse.ArgumentParser("Data Fetcher for live inference (model v9)")
    parser.add_argument("--config", default="", help="Path to config YAML")
    args = parser.parse_args()

    cur_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = args.config or os.path.join(cur_dir, "..", "config.yaml")
    output_csv = os.path.join(cur_dir, "..", "daily_inference_data.csv")

    if not os.path.exists(config_file):
        log.error("Config %s introuvable – arrêt.", config_file)
        return 1

    with open(config_file, "r") as fp:
        cfg = yaml.safe_load(fp) or {}

    tokens_daily: List[str] = cfg.get("extended_tokens_daily") or cfg.get("tokens_daily") or []
    if not tokens_daily:
        log.warning("Liste TOKENS_DAILY vide – CSV vide exporté.")
        pd.DataFrame().to_csv(output_csv, index=False)
        return 0

    lunar_api_key = cfg.get("lunarcrush", {}).get("api_key", "")
    binance_key = cfg.get("binance_api", {}).get("api_key", "")
    binance_sec = cfg.get("binance_api", {}).get("api_secret", "")

    lookback_days = 365
    sleep_between_tokens = 2.0
    max_retry = 3
    timeout_s = 25

    # Binance client (public endpoints ok même sans clés, mais on garde la config)
    binance_client = BinanceClient(binance_key or None, binance_sec or None)

    # Session HTTP réutilisable
    session = requests.Session()

    # -------------------- Benchmarks BTC / ETH -------------------- #
    log.info("Téléchargement BTC / ETH benchmarks…")
    btc_raw = fetch_lunar("BTC", lunar_api_key, days=lookback_days + 60,
                          max_retry=max_retry, timeout_s=timeout_s, session=session)
    eth_raw = fetch_lunar("ETH", lunar_api_key, days=lookback_days + 60,
                          max_retry=max_retry, timeout_s=timeout_s, session=session)

    # Sécurité: si close vide pour BTC/ETH, on traite comme échec
    if btc_raw is None or _safe_numeric_series(btc_raw, "close").empty:
        log.critical("Impossible de récupérer BTC (ou close vide) – arrêt.")
        return 1
    if eth_raw is None or _safe_numeric_series(eth_raw, "close").empty:
        log.critical("Impossible de récupérer ETH (ou close vide) – arrêt.")
        return 1

    btc_bench = prep_bench(btc_raw, "btc")
    eth_bench = prep_bench(eth_raw, "eth")

    # -------------------- Boucle principale tokens ---------------- #
    numeric_base_cols = [
        "open", "high", "low", "close", "volume", "market_cap",
        "galaxy_score", "alt_rank", "sentiment", "social_dominance", "market_dominance"
    ]

    dfs_tokens: List[pd.DataFrame] = []
    n_tot = len(tokens_daily)
    log.info("Traitement %d tokens…", n_tot)

    # Stats de fin
    stats: Dict[str, int] = {
        "total": n_tot,
        "kept": 0,
        "skip_fetch_none": 0,
        "skip_insufficient_rows": 0,
        "skip_close_empty": 0,
        "skip_price_mismatch": 0,
        "skip_exception": 0,
    }

    for idx, sym in enumerate(tokens_daily, 1):
        log.info("[%d/%d] %s", idx, n_tot, sym)

        try:
            raw = fetch_lunar(sym, lunar_api_key, days=lookback_days,
                              max_retry=max_retry, timeout_s=timeout_s, session=session)
            if raw is None:
                stats["skip_fetch_none"] += 1
                log.warning("[%s] LunarCrush: aucune donnée (raw=None) – skip", sym)
                continue

            if len(raw) < 60:
                stats["skip_insufficient_rows"] += 1
                log.warning("[%s] LunarCrush: données insuffisantes (len=%d) – skip", sym, len(raw))
                continue

            # --- Validation prix vs Binance (robuste) ----------------
            close_series = _safe_numeric_series(raw, "close")
            if close_series.empty:
                stats["skip_close_empty"] += 1
                log.warning("[%s] LunarCrush: close vide/après parsing -> skip. Colonnes=%s last_row=%s",
                            sym, list(raw.columns), _tail_as_dict(raw, 1))
                continue

            last_close = float(close_series.iloc[-1])
            if not verify_price(binance_client, sym, last_close):
                stats["skip_price_mismatch"] += 1
                log.warning("[%s] écart prix Binance > 20 %% (ou prix Binance indispo) – skip", sym)
                continue

            # -------------------------------------------------------- #
            # Préparation & indicateurs identiques training            #
            # -------------------------------------------------------- #
            df = raw.copy()

            # Assure présence colonnes attendues
            for col in numeric_base_cols:
                if col not in df.columns:
                    df[col] = np.nan

            df[numeric_base_cols] = df[numeric_base_cols].apply(pd.to_numeric, errors="coerce")
            # Parité backtest : NE PAS forcer volume NaN -> 0

            df_feat = compute_indicators_extended(df)
            if "date" not in df_feat.columns:
                # compute_indicators_extended est censée préserver date;
                # si ce n'est plus le cas, on stoppe ce token proprement.
                raise ValueError("compute_indicators_extended() n'a pas produit la colonne 'date'")

            df_feat.set_index("date", inplace=True)

            # ------------- Features étendues ------------------------ #
            df_feat["atr14_norm"] = df_feat["atr14"] / df_feat["close"].replace(0, np.nan)
            df_feat["price_change_norm_atr1d"] = df_feat["close"].diff() / df_feat["atr14"].shift()
            df_feat["rsi14_roc3d"] = df_feat["rsi14"].diff(3)
            df_feat["ma_slope_7d"] = calculate_slope(df_feat["ma_close_7d"])
            df_feat["ma_slope_14d"] = calculate_slope(df_feat["ma_close_14d"])

            bb = ta.volatility.BollingerBands(df_feat["close"], window=20, window_dev=2)
            mavg = bb.bollinger_mavg().replace(0, np.nan)
            df_feat["boll_width_norm"] = (bb.bollinger_hband() - bb.bollinger_lband()) / mavg

            df_feat["volume_norm_ma20"] = df_feat["volume"] / df_feat["volume"].rolling(20).mean()
            df_feat["galaxy_score_norm_ma7"] = df_feat["galaxy_score"] / df_feat["galaxy_score"].rolling(7).mean()
            df_feat["sentiment_ma_diff7"] = df_feat["sentiment"] - df_feat["sentiment"].rolling(7).mean()
            df_feat["alt_rank_roc1d"] = df_feat["alt_rank"].diff()
            df_feat["alt_rank_roc7d"] = df_feat["alt_rank"].diff(7)
            df_feat["obv_slope_5d"] = calculate_slope(df_feat["obv"])

            # ---- Deltas ------------------------------------------- #
            df_feat["delta_close_1d"] = df_feat["close"].pct_change(1)
            df_feat["delta_close_3d"] = df_feat["close"].pct_change(3)
            df_feat["delta_vol_1d"] = df_feat["volume"].pct_change(1)
            df_feat["delta_vol_3d"] = df_feat["volume"].pct_change(3)
            df_feat["delta_mcap_1d"] = df_feat["market_cap"].pct_change(1)
            df_feat["delta_mcap_3d"] = df_feat["market_cap"].pct_change(3)

            df_feat["delta_galaxy_1d"] = df_feat["galaxy_score"].diff(1)
            df_feat["delta_galaxy_3d"] = df_feat["galaxy_score"].diff(3)
            df_feat["delta_social_dom_1d"] = df_feat["social_dominance"].diff(1)
            df_feat["delta_social_dom_3d"] = df_feat["social_dominance"].diff(3)
            df_feat["delta_market_dom_1d"] = df_feat["market_dominance"].diff(1)
            df_feat["delta_market_dom_3d"] = df_feat["market_dominance"].diff(3)
            df_feat["delta_alt_rank_3d"] = df_feat["alt_rank"].diff(3)  # pas de 1d au training

            df_feat.reset_index(inplace=True)

            # ---- Fusion BTC / ETH -------------------------------- #
            merged = (df_feat.merge(btc_bench, on="date", how="left")
                             .merge(eth_bench, on="date", how="left"))

            merged["rsi_vs_btc"] = merged["rsi14"] - merged["btc_rsi"]
            merged["atr_norm_vs_btc"] = merged["atr14_norm"] - merged["btc_atr_norm"]

            avg_atr = (merged["btc_atr_norm"].fillna(0) + merged["eth_atr_norm"].fillna(0)) / 2
            merged["volatility_ratio_vs_market"] = merged["atr14_norm"] / avg_atr.replace(0, np.nan)

            # ---- Temporal features & metadata --------------------- #
            merged["dow"] = merged["date"].dt.dayofweek.astype("int8")
            merged["dom"] = merged["date"].dt.day.astype("int8")
            merged["month"] = merged["date"].dt.month.astype("int8")
            merged["symbol"] = sym

            # ---------- Parité CSV (alignement backtest) ----------- #
            merged["date_dt"] = pd.to_datetime(merged["date"], utc=True)

            merged.replace([np.inf, -np.inf], np.nan, inplace=True)

            dfs_tokens.append(merged)
            stats["kept"] += 1

        except Exception as e:
            stats["skip_exception"] += 1
            log.error("[%s] Exception pendant traitement token -> skip. Err=%s", sym, e, exc_info=True)
            continue

        finally:
            # On respecte l'intention "SLEEP_BETWEEN_TOKENS" pour limiter rate-limits
            if sleep_between_tokens and sleep_between_tokens > 0:
                time.sleep(sleep_between_tokens)

    # -------------------- Export ---------------------------------- #
    if not dfs_tokens:
        log.warning("Aucun token retenu – export CSV vide.")
        pd.DataFrame().to_csv(output_csv, index=False)
        log.info("Résumé: %s", stats)
        return 0

    df_all = pd.concat(dfs_tokens, ignore_index=True)
    df_all.sort_values(["symbol", "date_dt"], inplace=True)
    df_all.reset_index(drop=True, inplace=True)

    df_all.to_csv(output_csv, index=False)
    log.info("✅ daily_inference_data.csv écrit (%d lignes, %d colonnes)", len(df_all), len(df_all.columns))
    log.info("Résumé: %s", stats)
    print(f"[OK] => {output_csv} ({len(df_all)} rows, {len(df_all.columns)} cols)")
    return 0


if __name__ == "__main__":
    sys.exit(main())