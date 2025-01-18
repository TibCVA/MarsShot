#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
import ta

def compute_indicators_extended(df_in):
    """
    Calcule plus d'indicateurs :
      - RSI(14), RSI(30)
      - MACD => macd_std
      - ATR(14)
      - MA(7,14)
      - Stoch RSI
      - MFI(14)
      - Boll %b
      - OBV
      - ADX
    Return => DataFrame
    """
    df = df_in.copy()

    # RSI14, RSI30
    rsi14_ind = ta.momentum.RSIIndicator(df["close"], window=14)
    df["rsi14"] = rsi14_ind.rsi()

    rsi30_ind = ta.momentum.RSIIndicator(df["close"], window=30)
    df["rsi30"] = rsi30_ind.rsi()

    # MACD => macd_std
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

    # MA(7,14)
    df["ma_close_7d"] = df["close"].rolling(7).mean()
    df["ma_close_14d"] = df["close"].rolling(14).mean()

    # Stoch RSI
    stoch_obj = ta.momentum.StochRSIIndicator(
        close=df["close"], window=14, smooth1=3, smooth2=3
    )
    # Dans les versions >=0.7.0 => stochrsi_k(), stochrsi_d()
    df["stoch_rsi_k"] = stoch_obj.stochrsi_k()
    df["stoch_rsi_d"] = stoch_obj.stochrsi_d()

    # MFI(14)
    mfi_obj = ta.volume.MFIIndicator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        volume=df["volume"],
        window=14
    )
    df["mfi14"] = mfi_obj.money_flow_index()

    # Boll %b
    boll_obj = ta.volatility.BollingerBands(
        close=df["close"], window=20, window_dev=2
    )
    df["boll_percent_b"] = boll_obj.bollinger_pband()

    # OBV
    obv_obj = ta.volume.OnBalanceVolumeIndicator(
        close=df["close"],
        volume=df["volume"]
    )
    df["obv"] = obv_obj.on_balance_volume()

    # ADX
    adx_obj = ta.trend.ADXIndicator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14
    )
    df["adx"]     = adx_obj.adx()
    df["adx_pos"] = adx_obj.adx_pos()
    df["adx_neg"] = adx_obj.adx_neg()

    return df
