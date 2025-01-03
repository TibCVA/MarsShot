#!/usr/bin/env python3
# coding: utf-8

"""
Script Telegram + TradeExecutor pour le système MarsShot.
Sans placeholder : performance 1j,7j,30j calculée via klines Binance.

Commandes Telegram:
/port    => Etat global du portefeuille
/perf    => Performances de chaque position
/tokens  => Liste de tokens suivis
/add XXX => Ajoute un token
/remove XXX => Retire un token
/emergency => Tout vendre
Rapports automatiques 4x/jour, + notification transaction.

Fichiers requis:
- positions_store.py (load_state, save_state)
- utils.py (send_telegram_message)
- config.yaml (binance_api, telegrams, tokens_daily, strategy, etc.)
"""

import os
import logging
import datetime
import threading
import time
import yaml

# Telegram
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)
# Binance
from binance.client import Client

# On suppose que tu as ces fichiers (adaptés ci-dessous)
from positions_store import load_state, save_state
from utils import send_telegram_message  # => send_telegram_message(bot_token, chat_id, text)

########################################
# === Lecture config ===
########################################
CONFIG_FILE = "config.yaml"
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError("[ERREUR] config.yaml introuvable.")

with open(CONFIG_FILE, "r") as f:
    CONFIG = yaml.safe_load(f)

BINANCE_KEY    = CONFIG["binance_api"]["api_key"]
BINANCE_SECRET = CONFIG["binance_api"]["api_secret"]
BOT_TOKEN      = CONFIG["telegrams"].get("bot_token", None)
CHAT_ID        = CONFIG["telegrams"].get("chat_id", "7703664631")  # selon ta demande

if not BOT_TOKEN:
    raise ValueError("[ERREUR] bot_token manquant dans config.yaml => telegrams")

logging.basicConfig(level=logging.INFO)

########################################
# === Classe TradeExecutor (réécrite)
########################################
class TradeExecutor:
    def __init__(self, api_key, api_secret):
        self.client = Client(api_key, api_secret)

    def sell_all(self, symbol, qty):
        """
        Vend toute la qty sur la paire symbolUSDT (MARKET).
        Retourne la valeur en USDT (approx).
        """
        if qty <= 0:
            return 0.0
        real_qty = round(qty, 5)
        try:
            order = self.client.create_order(
                symbol=f"{symbol}USDT",
                side="SELL",
                type="MARKET",
                quantity=real_qty
            )
            fill_sum = 0.0
            fill_qty = 0.0
            for fill in order.get("fills", []):
                px  = float(fill["price"])
                qf  = float(fill["qty"])
                fill_sum += px*qf
                fill_qty += qf
            avg_px = fill_sum/fill_qty if fill_qty>0 else 0
            logging.info(f"[SELL_ALL] {symbol} qty={real_qty}, avg_px={avg_px:.4f}")

            # Notification Telegram
            notify_transaction("SELL", symbol, fill_qty, avg_px, fill_sum)
            return fill_sum
        except Exception as e:
            logging.error(f"[SELL_ALL ERROR] {symbol} => {e}")
            return 0.0

    def sell_partial(self, symbol, qty):
        return self.sell_all(symbol, qty)

    def buy(self, symbol, usdt_amount):
        """
        Achète en MARKET pour un certain montant USDT.
        Retourne (qty_effectivement_achetee, avg_px).
        """
        try:
            pair = f"{symbol}USDT"
            ticker = self.client.get_symbol_ticker(symbol=pair)
            px = float(ticker["price"])
            raw_qty = usdt_amount / px
            real_qty = round(raw_qty, 5)
            if real_qty <= 0:
                return (0.0, 0.0)

            order = self.client.create_order(
                symbol=pair,
                side="BUY",
                type="MARKET",
                quantity=real_qty
            )
            fill_sum = 0.0
            fill_qty = 0.0
            for fill in order.get("fills", []):
                fxp  = float(fill["price"])
                fxq  = float(fill["qty"])
                fill_sum += fxp*fxq
                fill_qty += fxq
            avg_px = fill_sum/fill_qty if fill_qty>0 else px
            logging.info(f"[BUY] {symbol} => qty={fill_qty}, avg_px={avg_px}")

            # Notification Telegram
            notify_transaction("BUY", symbol, fill_qty, avg_px, fill_sum)
            return (fill_qty, avg_px)
        except Exception as e:
            logging.error(f"[BUY ERROR] {symbol} => {e}")
            return (0.0, 0.0)

    def get_symbol_price(self, symbol):
        """
        Retourne le dernier prix (float) de symbol (ex: "FET" => FETUSDT).
        """
        pair = f"{symbol}USDT"
        tick = self.client.get_symbol_ticker(symbol=pair)
        return float(tick["price"])

    def get_kline_close(self, symbol, days=1):
        """
        Retourne le close (float) d'il y a X jours (ex.: 1 => hier),
        via l'API klines (interval=1d).
        """
        pair = f"{symbol}USDT"
        limit = days + 1
        klines = self.client.get_klines(
            symbol=pair,
            interval="1d",
            limit=limit
        )
        # klines: [ [open_time, open, high, low, close, volume, ..., close_time, ...], ...]
        if not klines:
            return None
        # => la bougie d'il y a X jours => klines[-(days)] en toute logique
        # ex. days=1 => klines[-1] c'est la plus récente => on veut "close" d'il y a 1 jour => klines[-2]
        idx = len(klines) - (days)
        if idx <= 0:
            return None
        c = klines[idx-1][4]  # on indexe idx-1
        return float(c)

########################################
# 4) Fonctions
########################################
def notify_transaction(action, sym, qty, avg_px, usdt_val):
    """
    Notifie sur Telegram qu'on a BUY/SELL symbol, qty, px, ~val en USDT.
    """
    if not CHAT_ID or not BOT_TOKEN:
        return
    msg = (
        f"[TRADE] {action} {sym}\n"
        f"QTY={qty:.4f}, PX={avg_px:.4f}, USDT~{usdt_val:.2f}"
    )
    send_telegram_message(BOT_TOKEN, CHAT_ID, msg)

def get_portfolio_state():
    """
    Renvoie un dict:
    {
      "positions": [
         {
           "symbol": "FET", 
           "qty": 123.45,
           "value_usdt": 234.56,
           "pnl_1d": +5.0,   # en %
           "pnl_7d": +8.2,
           "pnl_30d": +15.3,
           "pnl_since_entry": +25.4
         }, ...
      ],
      "total_value_usdt": 2345.67
    }
    => On se base sur positions_store + binance klines pour calculer perf
    """
    state = load_state(CONFIG["strategy"]["capital_initial"])
    positions = state["positions"]  # dict => { "FET": {...}, ... }
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)

    total_val = 0.0
    pos_list = []

    for sym, pos in positions.items():
        qty = pos["qty"]
        entry_px = pos["entry_price"]
        current_px = bexec.get_symbol_price(sym)
        val_usdt = current_px * qty
        total_val += val_usdt

        # Perf depuis l'entrée
        if entry_px>0:
            perf_since = (current_px - entry_px)/entry_px*100
        else:
            perf_since = 0.0

        # Perf 1j
        px_1d_ago = bexec.get_kline_close(sym, days=1)
        if px_1d_ago and px_1d_ago>0:
            pnl_1d = (current_px - px_1d_ago)/px_1d_ago*100
        else:
            pnl_1d = 0.0

        # Perf 7j
        px_7d_ago = bexec.get_kline_close(sym, days=7)
        if px_7d_ago and px_7d_ago>0:
            pnl_7d = (current_px - px_7d_ago)/px_7d_ago*100
        else:
            pnl_7d = 0.0

        # Perf 30j
        px_30d_ago = bexec.get_kline_close(sym, days=30)
        if px_30d_ago and px_30d_ago>0:
            pnl_30d = (current_px - px_30d_ago)/px_30d_ago*100
        else:
            pnl_30d = 0.0

        pos_list.append({
            "symbol": sym,
            "qty": round(qty,4),
            "value_usdt": round(val_usdt,2),
            "pnl_1d": round(pnl_1d,1),
            "pnl_7d": round(pnl_7d,1),
            "pnl_30d": round(pnl_30d,1),
            "pnl_since_entry": round(perf_since,1)
        })

    return {
        "positions": pos_list,
        "total_value_usdt": round(total_val,2)
    }

def list_tokens_tracked():
    return CONFIG["tokens_daily"]

def add_token_tracked(symbol):
    symbol = symbol.upper()
    if symbol not in CONFIG["tokens_daily"]:
        CONFIG["tokens_daily"].append(symbol)
        with open(CONFIG_FILE,"w") as f:
            yaml.dump(CONFIG, f)
        return True
    return False

def remove_token_tracked(symbol):
    symbol = symbol.upper()
    if symbol in CONFIG["tokens_daily"]:
        CONFIG["tokens_daily"].remove(symbol)
        with open(CONFIG_FILE,"w") as f:
            yaml.dump(CONFIG, f)
        return True
    return False

def emergency_out():
    """
    Vend TOUTES les positions et repasse en USDT.
    """
    st = load_state(CONFIG["strategy"]["capital_initial"])
    bexec = TradeExecutor(BINANCE_KEY, BINANCE_SECRET)
    for sym, pos in list(st["positions"].items()):
        qty = pos["qty"]
        val = bexec.sell_all(sym, qty)
        st["capital_usdt"] += val
        del st["positions"][sym]
    save_state(st)

########################################
# 5) Bot Telegram (polling)
########################################

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Bienvenue sur MarsShot_bot !\n"
        "Commandes:\n"
        "/port => Etat global\n"
        "/perf => Performance de chaque position\n"
        "/tokens => Liste tokens suivis\n"
        "/add <sym> => Ajouter\n"
        "/remove <sym> => Retirer\n"
        "/emergency => Vendre toutes positions\n"
    )
    await update.message.reply_text(msg)

async def cmd_port(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pf = get_portfolio_state()
    msg = f"Valeur Totale: {pf['total_value_usdt']} USDT\n\nPositions:\n"
    for p in pf["positions"]:
        msg += f"- {p['symbol']}: qty={p['qty']}, ~{p['value_usdt']} USDT\n"
    await update.message.reply_text(msg)

async def cmd_perf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pf = get_portfolio_state()
    msg = "Performance:\n"
    for p in pf["positions"]:
        msg += (
            f"- {p['symbol']} => 1j={p['pnl_1d']}%, 7j={p['pnl_7d']}%, 30j={p['pnl_30d']}%, sinceEntry={p['pnl_since_entry']}%\n"
        )
    await update.message.reply_text(msg)

async def cmd_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tokens = list_tokens_tracked()
    msg = "Tokens suivis:\n" + ", ".join(tokens)
    await update.message.reply_text(msg)

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args)<1:
        await update.message.reply_text("Usage: /add <symbol>")
        return
    sym = context.args[0].upper()
    ok = add_token_tracked(sym)
    if ok:
        await update.message.reply_text(f"{sym} ajouté à la liste.")
    else:
        await update.message.reply_text(f"{sym} déjà présent ou échec.")

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args)<1:
        await update.message.reply_text("Usage: /remove <symbol>")
        return
    sym = context.args[0].upper()
    ok = remove_token_tracked(sym)
    if ok:
        await update.message.reply_text(f"{sym} retiré !")
    else:
        await update.message.reply_text(f"{sym} pas trouvé ou échec.")

async def cmd_emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emergency_out()
    await update.message.reply_text("Toutes les positions ont été vendues !")

###################################
# Rapports automatiques 7h,12h,17h,22h
###################################
def send_portfolio_report():
    pf = get_portfolio_state()
    txt = f"[Auto-Report]\nValeurTotale: {pf['total_value_usdt']} USDT\n"
    if pf["positions"]:
        txt += f"Positions =>\n"
        for p in pf["positions"]:
            txt += f"  {p['symbol']}: ~{p['value_usdt']} USDT\n"
    send_telegram_message(BOT_TOKEN, CHAT_ID, txt)

def schedule_reports():
    while True:
        now = datetime.datetime.now()
        # toutes les h:00 => si hour in [7,12,17,22]
        if now.minute==0 and now.hour in [7,12,17,22]:
            send_portfolio_report()
            time.sleep(60)
        time.sleep(30)

def run_telegram_bot():
    # 1) Thread auto-reports
    t = threading.Thread(target=schedule_reports, daemon=True)
    t.start()

    # 2) Démarre le bot
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("port", cmd_port))
    app.add_handler(CommandHandler("perf", cmd_perf))
    app.add_handler(CommandHandler("tokens", cmd_tokens))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("emergency", cmd_emergency))

    logging.info("[TELEGRAM] Bot en polling... Ctrl+C pour stop.")
    app.run_polling()


if __name__=="__main__":
    run_telegram_bot()