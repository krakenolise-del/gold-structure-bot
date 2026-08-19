import os
import time
import requests
import yfinance as yf
import pandas as pd
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# TELEGRAM CONFIGURATION
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print(message)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

def check_market_structure():
    # Fetch Gold 15-minute candles
    df = yf.download(tickers="GC=F", interval="15m", period="5d", progress=False)
    
    if len(df) < 20:
        return

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df['High_20'] = df['High'].rolling(20).max()
    df['Low_20'] = df['Low'].rolling(20).min()

    last = df.iloc[-2]
    prev = df.iloc[-3]
    recent_high = df['High'].iloc[-22:-2].max()
    recent_low = df['Low'].iloc[-22:-2].min()

    close_price = round(float(last['Close']), 2)

    # 1. LIQUIDITY SWEEP BUY SETUP
    if prev['Low'] < recent_low and last['Close'] > recent_low and last['Close'] > last['Open']:
        sl = round(float(prev['Low']) - 0.50, 2)
        tp = round(close_price + ((close_price - sl) * 2), 2)
        
        msg = (
            "🟢 *GOLD (XAUUSD) BUY SETUP*\n\n"
            f"• *Reason:* Liquidity Sweep Low + CHoCH Reversal\n"
            f"• *Entry Price:* {close_price}\n"
            f"• *Stop Loss (SL):* {sl}\n"
            f"• *Take Profit (TP):* {tp}\n"
            f"• *Timeframe:* M15"
        )
        send_telegram(msg)

    # 2. LIQUIDITY SWEEP SELL SETUP
    elif prev['High'] > recent_high and last['Close'] < recent_high and last['Close'] < last['Open']:
        sl = round(float(prev['High']) + 0.50, 2)
        tp = round(close_price - ((sl - close_price) * 2), 2)
        
        msg = (
            "🔴 *GOLD (XAUUSD) SELL SETUP*\n\n"
            f"• *Reason:* Liquidity Sweep High + CHoCH Reversal\n"
            f"• *Entry Price:* {close_price}\n"
            f"• *Stop Loss (SL):* {sl}\n"
            f"• *Take Profit (TP):* {tp}\n"
            f"• *Timeframe:* M15"
        )
        send_telegram(msg)

if __name__ == "__main__":
    send_telegram("🚀 *Gold Market Structure Bot Active & Scanning (M15)...*")
    while True:
        try:
            check_market_structure()
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(900)  # Check every 15 minutes
  
