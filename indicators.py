#!/usr/bin/env python3
# coding: utf-8

import pandas as pd
import numpy as np
import ta

def compute_rsi_macd_atr(df):
    """
    Calcule RSI(14), MACD(12,26,9) et ATR(14) sur df=[date, open, high, low, close, volume, ...].
    
    Stratégie :
      1) Convertir open/high/low/close/volume en float (éventuels "0" => 0.0).
      2) Pour chaque ligne, si open/high/low/close == 0 ou NaN => on force ces 4 colonnes à NaN.
         (On considère qu'il n'y a pas de données exploitables ce jour-là pour le prix.)
      3) On retire ensuite physiquement ces lignes du DataFrame (dropna sur open, high, low, close),
         de sorte que ta ne calculera pas d'indicateurs sur des valeurs fantaisistes.
      4) On calcule RSI(14), macd_diff, et ATR(14).
      5) On renvoie le DataFrame final (avec de nouvelles colonnes : 'rsi', 'macd', 'atr').

    Objectif : Éviter que ta calcule un RSI=100 (ou 0) sur des lignes vides.
    """

    # Copie pour ne pas altérer df directement
    dff = df.copy()

    # Convertir en float
    for col in ["open", "high", "low", "close", "volume"]:
        dff[col] = pd.to_numeric(dff[col], errors="coerce")

    # Étape 2) Masque booléen : True si l'une des 4 colonnes (open,high,low,close) est 0 ou NaN
    # On le décompose en 2 sous-masques pour plus de clarté
    zero_mask = (
        (dff["open"] == 0) |
        (dff["high"] == 0) |
        (dff["low"]  == 0) |
        (dff["close"]== 0)
    )

    nan_mask = (
        dff["open"].isna() |
        dff["high"].isna() |
        dff["low"].isna()  |
        dff["close"].isna()
    )

    # Masque final
    any_zero_or_nan = zero_mask | nan_mask

    # Sur ces lignes, on force open/high/low/close à NaN
    dff.loc[any_zero_or_nan, ["open", "high", "low", "close"]] = np.nan

    # Étape 3) On retire maintenant physiquement toutes ces lignes (any => si l'une des 4 colonnes est NaN)
    dff.dropna(subset=["open","high","low","close"], how="any", inplace=True)

    # Si tout est parti, on peut retourner directement
    if dff.empty:
        # On retourne le df vide, ou éventuellement on recrée quand même la structure attendue
        # mais par cohérence on renvoie dff qui est vide => l'appelant gérera
        return dff

    # Étape 4) Calcul du RSI(14)
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