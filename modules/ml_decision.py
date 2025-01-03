import os
import joblib
import numpy as np

MODEL_PATH = "model.pkl"
_model = None

def load_model():
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError("[ERREUR] model.pkl introuvable.")
        _model = joblib.load(MODEL_PATH)
    return _model

def predict_probability(features_dict):
    """
    features_dict = {
      'close':..., 'volume':..., 'market_cap':...,
      'rsi':..., 'macd':..., 'atr':...,
      'btc_daily_change':..., 'eth_daily_change':...
    }
    """
    model = load_model()
    arr = np.array([
        features_dict.get("close", 0),
        features_dict.get("volume", 0),
        features_dict.get("market_cap", 0),
        features_dict.get("rsi", 50),
        features_dict.get("macd", 0),
        features_dict.get("atr", 0),
        features_dict.get("btc_daily_change", 0),
        features_dict.get("eth_daily_change", 0)
    ]).reshape(1, -1)
    prob = model.predict_proba(arr)[0][1]
    return prob