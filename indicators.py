#!/usr/bin/env python3
# coding: utf-8

import pandas as pd
import numpy as np
import ta

def compute_rsi_macd_atr(df):
    """
    Calcule RSI(14), MACD(12,26,9) et ATR(14) sur df=[date, open, high, low, close, volume, ...].
    Ici, TOUTES les valeurs = 0 dans open/high/low/close sont considérées comme « pas de donnée »,
    donc transformées en NaN avant le calcul des indicateurs.

    Colonnes de sortie créées :
      - df["rsi"]
      - df["macd"]
      - df["atr"]

    Remarque :
      Si vous souhaitez imposer un RSI=0 pour les lignes avec close=0, dé-commentez le bloc à la fin.
    """

    # Copie pour ne pas modifier l'original
    dff = df.copy()

    # Convertir "open/high/low/close/volume" en float
    for col in ["open", "high", "low", "close", "volume"]:
        dff[col] = pd.to_numeric(dff[col], errors="coerce")

    # Identifier où close=0 => c'est un "pas de donnée"
    mask_zero = (dff["close"] == 0) | (dff["close"].isna())
    # On applique la même logique aux colonnes open/high/low
    # Car s'il n'y a pas de close, souvent open/high/low sont 0 => pas de donnée
    for col in ["open","high","low"]:
        # Si la valeur =0, on la met en NaN
        zero_mask_col = (dff[col] == 0) | (dff[col].isna())
        dff.loc[zero_mask_col, col] = np.nan

    # On met close=NaN aussi quand c'est 0
    dff.loc[mask_zero, "close"] = np.nan

    # Calcul du RSI
    rsi_ind = ta.momentum.RSIIndicator(dff["close"], window=14)
    dff["rsi"] = rsi_ind.rsi()

    # Calcul du MACD (diff)
    macd_ind = ta.trend.MACD(
        close=dff["close"],
        window_slow=26,
        window_fast=12,
        window_sign=9
    )
    dff["macd"] = macd_ind.macd_diff()

    # Calcul du ATR
    atr_ind = ta.volatility.AverageTrueRange(
        high=dff["high"],
        low=dff["low"],
        close=dff["close"],
        window=14
    )
    dff["atr"] = atr_ind.average_true_range()

    # Optionnel : si vous voulez imposer RSI=0 sur les lignes où close=NaN (i.e. où close=0 initialement),
    # dé-commentez la ligne ci-dessous :
    # dff.loc[mask_zero, "rsi"] = 0.0

    return dff