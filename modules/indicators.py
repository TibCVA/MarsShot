#!/usr/bin/env python3
# coding: utf-8

import pandas as pd
import numpy as np
import ta

def compute_rsi_macd_atr(df):
    """
    Calcule RSI(14), MACD(12,26,9) et ATR(14) sur df=[date, open, high, low, close, volume, ...].
    
    Stratégie :
      1) Convertir open/high/low/close/volume en float (0 => 0.0).
      2) Forcer NaN si open/high/low/close=0 ou inexistant => dropna
      3) RSI(14), MACD diff(12,26,9), ATR(14).
    """

    dff = df.copy()

    # Convertir en float
    for col in ["open", "high", "low", "close", "volume"]:
        dff[col] = pd.to_numeric(dff[col], errors="coerce")

    zero_mask = (
        (dff["open"] == 0) |
        (dff["high"] == 0) |
        (dff["low"] == 0)  |
        (dff["close"]== 0)
    )
    nan_mask = (
        dff["open"].isna() |
        dff["high"].isna() |
        dff["low"].isna()  |
        dff["close"].isna()
    )
    any_zero_or_nan = zero_mask | nan_mask
    dff.loc[any_zero_or_nan, ["open","high","low","close"]] = np.nan

    dff.dropna(subset=["open","high","low","close"], how="any", inplace=True)
    if dff.empty:
        return dff

    # RSI(14)
    rsi_ind = ta.momentum.RSIIndicator(dff["close"], window=14)
    dff["rsi"] = rsi_ind.rsi()

    # MACD => on stocke macd_diff
    macd_ind = ta.trend.MACD(
        close=dff["close"],
        window_slow=26,
        window_fast=12,
        window_sign=9
    )
    dff["macd"] = macd_ind.macd_diff()

    # ATR(14)
    atr_ind = ta.volatility.AverageTrueRange(
        high=dff["high"],
        low=dff["low"],
        close=dff["close"],
        window=14
    )
    dff["atr"] = atr_ind.average_true_range()

    return dff