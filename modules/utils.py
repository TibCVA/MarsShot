import requests
import logging

def send_telegram_message(config, msg):
    tg = config.get("telegrams",{})
    bot_token = tg.get("bot_token","")
    chat_id = tg.get("chat_id","")
    if not(bot_token and chat_id):
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {"chat_id": chat_id,"text": msg}
    try:
        requests.post(url, data=data)
    except Exception as e:
        logging.error(f"[Telegram Error] {e}")

