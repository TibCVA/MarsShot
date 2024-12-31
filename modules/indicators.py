#!/usr/bin/env python3
# coding: utf-8

import pandas as pd
import numpy as np
import ta

def compute_rsi_macd_atr(df):
    """
    Calcule RSI(14), MACD(12,26,9) et ATR(14) sur df=[date, open, high, low, close, volume, ...].
    
    Approche très stricte :
      - Si l'une de (open, high, low, close) est 0 ou NaN => on considère que cette ligne n'a pas
        de données valables => on force open=high=low=close=NaN.
      - On convertit ensuite volume aussi en float, mais on ne force pas volume=NaN si =0. 
        (Le volume peut légitimement être 0, ou absent, selon vos besoins.)
      - Sur ces lignes, la librairie `ta` ne calculera pas d'indicateurs. 
      
    Ceci évite un RSI=100 dans les cas où la ligne n'est pas réellement exploitable.
    """

    # Copie pour ne pas altérer df directement
    dff = df.copy()

    # Convertir "open/high/low/close/volume" en float
    for col in ["open", "high", "low", "close", "volume"]:
        dff[col] = pd.to_numeric(dff[col], errors="coerce")

    # 1) Identifier les lignes "invalides" => mask si l'une de open/high/low/close == 0 ou est NaN
    #   any_zero_mask = (open==0) OR (high==0) OR (low==0) OR (close==0)
    #   ou tout simplement, si min(...) == 0 -> c'est qu'au moins un vaut 0
    #   + si un est NaN => row invalid => handle via min( ) ?
    #   => plus simple: on check individuellement
    any_zero_or_nan_mask = (
        (dff["open"].isna() | (dff["open"] == 0)) |
        (dff["high"].isna() | (dff["high"] == 0)) |
        (dff["low"].isna()  | (dff["low"]  == 0)) |
        (dff["close"].isna()| (dff["close"]== 0))
    )

    # Sur ces lignes, on met open/high/low/close=NaN => la librairie ta les ignorera
    dff.loc[any_zero_or_nan_mask, ["open","high","low","close"]] = np.nan

    # 2) Calcul du RSI (sur 14 jours)
    rsi_ind = ta.momentum.RSIIndicator(dff["close"], window=14)
    dff["rsi"] = rsi_ind.rsi()

    # 3) Calcul du MACD (macd_diff)
    macd_ind = ta.trend.MACD(
        close=dff["close"],
        window_slow=26,
        window_fast=12,
        window_sign=9
    )
    dff["macd"] = macd_ind.macd_diff()

    # 4) Calcul du ATR(14)
    atr_ind = ta.volatility.AverageTrueRange(
        high=dff["high"],
        low=dff["low"],
        close=dff["close"],
        window=14
    )
    dff["atr"] = atr_ind.average_true_range()

    return dff