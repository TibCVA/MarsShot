import joblib
import numpy as np

model = joblib.load("/app/model.pkl")

def get_buy_signal(features, threshold=0.7):
    arr = np.array([
        features["price"],
        features["volume"],
        features["market_cap"],
        features["holders"],
        features["sentiment_score"],
        features["ATR"],
        features["RSI"],
        features["MACD"]
    ]).reshape(1,-1)

    prob = model.predict_proba(arr)[0][1]
    return (prob >= threshold), prob

