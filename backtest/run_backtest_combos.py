#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import pandas as pd
import numpy as np
import joblib
from datetime import datetime, timedelta

########################################
# PARAMÈTRES GLOBAUX DE BACKTEST
########################################
BACKTEST_CSV     = "backtest_data.csv"   # CSV sur ~3 mois, contenant colonnes "date","symbol", features...
MODEL_FILE       = "model.pkl"           # Votre pipeline final (LightGBM, etc.)
LOG_FILE         = "run_backtest_advanced.log"

CAPITAL_INITIAL  = 821.0

BUY_THRESHOLDS   = [0.9, 0.8, 0.75, 0.7, 0.65, 0.6]
SELL_THRESHOLDS  = [0.25, 0.3, 0.35, 0.4]

# Paramètres RISK MANAGEMENT identiques à votre "main + risk_manager"
STOP_LOSS_PCT             = 0.25
PARTIAL_TAKE_PROFIT_PCT   = 0.45
PARTIAL_TAKE_PROFIT_RATIO = 0.40
TRAILING_TRIGGER_PCT      = 1.8
TRAILING_PCT              = 0.25
BIG_GAIN_EXCEPTION_PCT    = 2.0

MIN_USDT_TO_BUY           = 10.0  # Seuil minimum par trade

########################################
logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.info("=== START run_backtest_advanced ===")


def main():
    # Vérif existence CSV + modèle
    if not os.path.exists(BACKTEST_CSV):
        print(f"[ERROR] {BACKTEST_CSV} introuvable.")
        return
    if not os.path.exists(MODEL_FILE):
        print(f"[ERROR] {MODEL_FILE} introuvable.")
        return

    # Chargement du modèle : pipeline + éventuel threshold
    loaded = joblib.load(MODEL_FILE)
    if isinstance(loaded, tuple):
        pipeline, custom_thresh = loaded
        logging.info(f"[INFO] Modele charge => pipeline + threshold={custom_thresh}")
    else:
        pipeline      = loaded
        custom_thresh = None

    # Lecture du CSV
    df = pd.read_csv(BACKTEST_CSV)
    if df.empty:
        print(f"[WARN] {BACKTEST_CSV} est vide => abort.")
        return

    # Conversion date => datetime
    df["date_dt"] = pd.to_datetime(df["date"])
    df.sort_values(["date_dt","symbol"], ascending=[True, True], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Les features (SANS 'label'), comme dans ml_decision
    FEATURES = [
        "delta_close_1d","delta_close_3d","delta_vol_1d","delta_vol_3d",
        "rsi14","rsi30","ma_close_7d","ma_close_14d","atr14","macd_std",
        "stoch_rsi_k","stoch_rsi_d","mfi14","boll_percent_b","obv",
        "adx","adx_pos","adx_neg",
        "btc_daily_change","btc_3d_change","eth_daily_change","eth_3d_change",
        "delta_mcap_1d","delta_mcap_3d",
        "galaxy_score","delta_galaxy_score_3d",
        "alt_rank","delta_alt_rank_3d",
        "sentiment",
        "social_dominance","market_dominance",
        "delta_social_dom_3d","delta_market_dom_3d"
    ]
    df.dropna(subset=FEATURES, inplace=True)

    # On va stocker le résultat final (pour le combo summary)
    table_rows = []
    # On veut AUSSI stocker tous les trades de tous combos => pour analyser la distribution
    all_closed_trades = []

    def simulate_backtest(dfin, pipeline, buy_th, sell_th):
        dfc = dfin.copy()
        all_dates = dfc["date_dt"].unique()

        capital = CAPITAL_INITIAL
        holdings = {}         # { "SYM": qty, ... }
        positions_meta = {}   # { "SYM": { entry_px, did_skip_sell_once, partial_sold, max_price, entry_date, ... } }
        closed_trades = []    # liste de dicts (symbol, entry_date, exit_date, buy_px, sell_px, etc.)
        buy_signals   = []    # pour classifier +5% / small_gain / losing

        equity_curve = []

        for day_i, d in enumerate(sorted(all_dates)):
            day_rows = dfc[dfc["date_dt"]==d]
            if day_rows.empty:
                continue

            # 1) Appliquer "risk_manager intraday" => stoploss / partial / trailing
            for i2, row2 in day_rows.iterrows():
                sym = row2["symbol"]
                if sym not in holdings:
                    continue
                real_qty = holdings[sym]
                current_px= float(row2["close"])
                pm = positions_meta[sym]
                entry_px= pm["entry_px"]
                ratio= (current_px / entry_px) if entry_px>0 else 1.0

                # STOP-LOSS
                if ratio <= (1 - STOP_LOSS_PCT):
                    val= real_qty* current_px
                    capital+= val
                    # On log le trade fermé
                    closed_trades.append({
                        "symbol": sym,
                        "entry_date": pm["entry_date"],
                        "exit_date": d,
                        "buy_price": pm["entry_px"],
                        "sell_price": current_px,
                        "pct_change": (ratio - 1.0)*100,
                        "reason": "STOPLOSS"
                    })
                    holdings.pop(sym)
                    positions_meta.pop(sym)
                    continue

                # PARTIAL
                if (not pm["partial_sold"]) and (ratio >= (1 + PARTIAL_TAKE_PROFIT_PCT)):
                    qty_to_sell= real_qty* PARTIAL_TAKE_PROFIT_RATIO
                    val= qty_to_sell* current_px
                    capital+= val
                    new_qty= real_qty- qty_to_sell
                    holdings[sym]= new_qty
                    pm["partial_sold"]= True
                    # On log un "trade partiel"
                    closed_trades.append({
                        "symbol": sym,
                        "entry_date": pm["entry_date"],
                        "exit_date": d,
                        "buy_price": pm["entry_px"],
                        "sell_price": current_px,
                        "pct_change": (current_px / pm["entry_px"] - 1.0)*100,
                        "reason": "PARTIAL_SELL"
                    })

                # TRAILING
                if ratio >= TRAILING_TRIGGER_PCT:
                    mx= pm["max_price"]
                    if current_px> mx:
                        pm["max_price"]= current_px
                    else:
                        # si current_px <= mx*(1-TRAILING_PCT), on vend tout
                        if current_px <= mx*(1-TRAILING_PCT):
                            val= real_qty* current_px
                            capital+= val
                            closed_trades.append({
                                "symbol": sym,
                                "entry_date": pm["entry_date"],
                                "exit_date": d,
                                "buy_price": pm["entry_px"],
                                "sell_price": current_px,
                                "pct_change": (current_px / pm["entry_px"] - 1.0)*100,
                                "reason": "TRAILING_STOP"
                            })
                            holdings.pop(sym)
                            positions_meta.pop(sym)
                            continue

            # 2) SELL logic => prob < sell_th EOD
            #    => sauf big_gain_exception
            # predict
            X_day = day_rows[FEATURES].values
            prob_1 = pipeline.predict_proba(X_day)[:,1]
            day_rows["prob"] = prob_1

            for i2, row2 in day_rows.iterrows():
                sym = row2["symbol"]
                if sym not in holdings:
                    continue
                p= row2["prob"]
                current_px= float(row2["close"])
                pm= positions_meta[sym]
                entry_px= pm["entry_px"]
                ratio= (current_px / entry_px) if entry_px>0 else 1.0

                if p< sell_th:
                    if (ratio>= BIG_GAIN_EXCEPTION_PCT) and (not pm["did_skip_sell_once"]):
                        pm["did_skip_sell_once"]= True
                    else:
                        real_qty= holdings[sym]
                        val= real_qty* current_px
                        capital+= val
                        closed_trades.append({
                            "symbol": sym,
                            "entry_date": pm["entry_date"],
                            "exit_date": d,
                            "buy_price": pm["entry_px"],
                            "sell_price": current_px,
                            "pct_change": (ratio -1.0)*100,
                            "reason": "SELL_logic"
                        })
                        holdings.pop(sym)
                        positions_meta.pop(sym)

            # 3) BUY => top 5
            # filtrer p >= buy_th
            buy_candidates= []
            for i2, row2 in day_rows.iterrows():
                sym= row2["symbol"]
                if sym in holdings:
                    continue
                p= float(row2["prob"])
                if p>= buy_th:
                    buy_candidates.append( (sym, p, float(row2["close"])) )

            buy_candidates.sort(key=lambda x:x[1], reverse=True)
            buy_candidates= buy_candidates[:5]

            if buy_candidates and capital> MIN_USDT_TO_BUY:
                alloc= capital/ len(buy_candidates)
                for (sym, p, close_px) in buy_candidates:
                    if alloc< MIN_USDT_TO_BUY:
                        continue
                    qty_bought= alloc/ close_px
                    capital-= alloc
                    holdings[sym]= qty_bought
                    positions_meta[sym]= {
                        "entry_px": close_px,
                        "entry_date": d,
                        "did_skip_sell_once": False,
                        "partial_sold": False,
                        "max_price": close_px
                    }
                    # Pour classification +5% => on enregistre day_i (l'index) 
                    # On fera la classification 2 jours plus tard
                    buy_signals.append({
                        "day_index": day_i,
                        "symbol": sym,
                        "buy_price": close_px,
                        "classified": False
                    })

            # 4) calcul equity du jour => capital + holdings
            eq_val = capital
            for sy, q_ in holdings.items():
                row_ = day_rows[ day_rows["symbol"]== sy ]
                if not row_.empty:
                    c_ = float(row_["close"].values[0])
                    eq_val+= q_* c_
            equity_curve.append( (d, eq_val) )

            # 5) classification => signaux d'achat de day_i - 2
            day_ref = day_i - 2
            if day_ref>=0:
                # On regarde ceux qui ont day_index= day_ref
                for bsig in buy_signals:
                    if (bsig["day_index"]== day_ref) and (not bsig["classified"]):
                        # check ratio 48h => close d'aujourd'hui / buy_px
                        buy_px= bsig["buy_price"]
                        # on cherche row du day_i, symbol => close
                        row_2 = day_rows[ day_rows["symbol"]== bsig["symbol"] ]
                        if not row_2.empty:
                            c_48 = float(row_2["close"].values[0])
                            ratio_48= (c_48/ buy_px) if buy_px>0 else 1.0
                            if ratio_48>=1.05:
                                bsig["result"] = "correct_5pct"
                            elif ratio_48>1.0:
                                bsig["result"] = "small_gain"
                            else:
                                bsig["result"] = "loss"
                            bsig["classified"]= True

        # fin de la boucle sur days
        # cloture => on vend tout
        if len(holdings)>0:
            last_day = sorted(all_dates)[-1]
            last_rows= dfc[ dfc["date_dt"]== last_day ]
            for sy, q_ in holdings.items():
                row_ = last_rows[last_rows["symbol"]== sy]
                if not row_.empty:
                    c_ = float(row_["close"].values[0])
                else:
                    c_ = 0
                val= q_* c_
                capital+= val
                pm= positions_meta[sy]
                closed_trades.append({
                    "symbol": sy,
                    "entry_date": pm["entry_date"],
                    "exit_date": last_day,
                    "buy_price": pm["entry_px"],
                    "sell_price": c_,
                    "pct_change": (c_/ pm["entry_px"] -1.0)*100 if pm["entry_px"]>0 else 0,
                    "reason": "END_OF_BACKTEST"
                })
            holdings.clear()
            positions_meta.clear()

        final_equity = capital
        final_pnl    = final_equity - CAPITAL_INITIAL

        # On compte classification
        correct_5pct=0
        small_gain=0
        losing=0
        total_buys=0
        for bs in buy_signals:
            if bs.get("classified", False):
                total_buys+=1
                if bs["result"]=="correct_5pct":
                    correct_5pct+=1
                elif bs["result"]=="small_gain":
                    small_gain+=1
                else:
                    losing+=1

        closed_df = pd.DataFrame(closed_trades)
        # On peut calculer la distribution de "pct_change" ...
        equity_df = pd.DataFrame(equity_curve, columns=["date","equity"])

        return {
            "final_equity": final_equity,
            "pnl": final_pnl,
            "nb_buys": total_buys,
            "correct_5pct": correct_5pct,
            "small_gain": small_gain,
            "losing": losing,
            "closed_trades": closed_df,
            "equity_curve": equity_df
        }


    # On lance la boucle sur (buy_th, sell_th)
    for buy_th in BUY_THRESHOLDS:
        for sell_th in SELL_THRESHOLDS:
            logging.info(f"[COMBO] buy={buy_th}, sell={sell_th}")
            result = simulate_backtest(df, pipeline, buy_th, sell_th)
            feq = result["final_equity"]
            pnl= result["pnl"]
            nb= result["nb_buys"]
            cor= result["correct_5pct"]
            smg= result["small_gain"]
            los= result["losing"]
            # stats
            pc_cor= (cor/ nb*100) if nb>0 else 0
            pc_smg= (smg/ nb*100) if nb>0 else 0
            pc_los= (los/ nb*100) if nb>0 else 0

            table_rows.append({
                "buy_th": buy_th,
                "sell_th": sell_th,
                "final_equity": feq,
                "pnl": pnl,
                "nb_buys": nb,
                "correct_5pct": cor,
                "small_gain": smg,
                "losing": los,
                "pc_correct_5pct": pc_cor,
                "pc_small_gain": pc_smg,
                "pc_losing": pc_los
            })

            # On sauvegarde dans all_closed_trades en rajoutant des colonnes buy_th / sell_th
            cdf= result["closed_trades"].copy()
            if not cdf.empty:
                cdf["buy_th"]= buy_th
                cdf["sell_th"]= sell_th
                all_closed_trades.append(cdf)

            # Sauvegarde l'equity curve dans un CSV distinct
            eqdf= result["equity_curve"].copy()
            eqdf["buy_th"] = buy_th
            eqdf["sell_th"] = sell_th
            out_eq_name= f"equity_curve_buy{buy_th}_sell{sell_th}.csv"
            eqdf.to_csv(out_eq_name, index=False)

    # On construit le df final combos
    combos_df = pd.DataFrame(table_rows)
    combos_df.sort_values(["buy_th","sell_th"], ascending=[False, True], inplace=True)
    combos_df.to_csv("backtest_results.csv", index=False)
    print("[OK] => backtest_results.csv generated.")
    print(combos_df)

    # On exporte aussi la concat de tous les trades fermés
    if len(all_closed_trades)>0:
        cdf_all = pd.concat(all_closed_trades, ignore_index=True)
        cdf_all.to_csv("closed_trades_ALL.csv", index=False)
        # On peut déjà afficher des stats sur la distri de 'pct_change'
        mean_ = cdf_all["pct_change"].mean()
        std_  = cdf_all["pct_change"].std()
        mx_   = cdf_all["pct_change"].max()
        mn_   = cdf_all["pct_change"].min()
        print(f"Distribution pct_change sur TOUTES combos => mean={mean_:.2f}%, std={std_:.2f}, min={mn_:.2f}%, max={mx_:.2f}%")
    else:
        print("[INFO] Pas de trades fermes => all_closed_trades est vide.")


if __name__=="__main__":
    main()
