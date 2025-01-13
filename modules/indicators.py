#!/usr/bin/env python3
# coding: utf-8

import pandas as pd
import numpy as np
import ta  # pip install ta

def compute_indicators(df_in):
    """
    Calcule dans df_in :
      - rsi14, rsi30
      - macd_std (macd diff) => macd(12,26,9)
      - atr14
      - ma_close_7d, ma_close_14d

    Retourne un df enrichi de ces colonnes.

    Prérequis : df_in a déjà 'close','high','low','volume' convertis en float,
    sans lignes NaN (pour open/high/low/close).
    """

    df = df_in.copy()

    # RSI(14)
    rsi14_ind = ta.momentum.RSIIndicator(df["close"], window=14)
    df["rsi14"] = rsi14_ind.rsi()

    # RSI(30)
    rsi30_ind = ta.momentum.RSIIndicator(df["close"], window=30)
    df["rsi30"] = rsi30_ind.rsi()

    # MACD => macd_diff
    macd_obj = ta.trend.MACD(
        close=df["close"],
        window_slow=26,
        window_fast=12,
        window_sign=9
    )
    df["macd_std"] = macd_obj.macd_diff()

    # ATR(14)
    atr_obj = ta.volatility.AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14
    )
    df["atr14"] = atr_obj.average_true_range()

    # MA close 7d, 14d
    df["ma_close_7d"] = df["close"].rolling(7).mean()
    df["ma_close_14d"] = df["close"].rolling(14).mean()

    return df
