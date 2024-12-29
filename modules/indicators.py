import pandas as pd
import ta

def compute_indicators(df):
    """
    df => [date, open, high, low, close, volume, market_cap]
    => calcule ATR(14), RSI(14), MACD(12,26,9)
    """
    dff = df.copy()
    for col in ["open","high","low","close","volume"]:
        dff[col] = pd.to_numeric(dff[col], errors="coerce").fillna(0)

    # ATR
    atr_ind = ta.volatility.AverageTrueRange(
        high=dff["high"],
        low=dff["low"],
        close=dff["close"],
        window=14
    )
    dff["ATR"] = atr_ind.average_true_range()

    # RSI
    rsi_ind = ta.momentum.RSIIndicator(dff["close"], window=14)
    dff["RSI"] = rsi_ind.rsi()

    # MACD
    macd_ind = ta.trend.MACD(
        close=dff["close"],
        window_slow=26,
        window_fast=12,
        window_sign=9
    )
    dff["MACD"] = macd_ind.macd_diff()

    return dff

