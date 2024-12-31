import pandas as pd
import ta

def compute_rsi_macd_atr(df):
    """
    Calcule RSI, MACD, ATR sur df=[date, open, high, low, close, volume, ...].
    """
    dff = df.copy()
    # Convert numeric
    for col in ["open","high","low","close","volume"]:
        dff[col] = pd.to_numeric(dff[col], errors="coerce").fillna(0)

    # RSI
    rsi_ind = ta.momentum.RSIIndicator(dff["close"], window=14)
    dff["rsi"] = rsi_ind.rsi()

    # MACD
    macd_ind = ta.trend.MACD(
        dff["close"],
        window_slow=26,
        window_fast=12,
        window_sign=9
    )
    dff["macd"] = macd_ind.macd_diff()

    # ATR
    atr_ind = ta.volatility.AverageTrueRange(
        high=dff["high"],
        low=dff["low"],
        close=dff["close"],
        window=14
    )
    dff["atr"] = atr_ind.average_true_range()

    return dff