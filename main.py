import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

# CONFIGURATION
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# GLOBAL MEMORY FOR BACKGROUND STRUCTURE PARSING
LATEST_STRUCTURE = {
    "current_price": None,
    "trend": None,
    "swing_high": None,
    "swing_low": None,
    "sl": None,
    "tp": None,
    "structure_desc": None,
    "updated_at": 0
}

# 1. KEEP-ALIVE SERVER FOR RENDER
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Active")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# 2. CONTINUOUS BACKGROUND STRUCTURE ENGINE
def background_structure_engine():
    global LATEST_STRUCTURE
    headers = {"User-Agent": "Mozilla/5.0"}
    url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=15m&range=2d"
    
    while True:
        try:
            r = requests.get(url, headers=headers, timeout=10).json()
            result = r['chart']['result'][0]
            quote = result['indicators']['quote'][0]
            
            highs = quote['high']
            lows = quote['low']
            closes = quote['close']
            
            valid_candles = [(h, l, c) for h, l, c in zip(highs, lows, closes) if h and l and c]
            
            if len(valid_candles) >= 20:
                recent_highs = [x[0] for x in valid_candles[-20:]]
                recent_lows = [x[1] for x in valid_candles[-20:]]
                current_price = valid_candles[-1][2]
                
                swing_high = max(recent_highs)
                swing_low = min(recent_lows)
                mid_point = (swing_high + swing_low) / 2
                
                # Check structure position relative to recent swings
                if current_price > mid_point:
                    trend = "BUY"
                    sl = round(swing_low - 0.50, 2)
                    tp = round(current_price + ((current_price - sl) * 2), 2)
                    structure_desc = "Bullish (Trading in upper half of 15m range)"
                else:
                    trend = "SELL"
                    sl = round(swing_high + 0.50, 2)
                    tp = round(current_price - ((sl - current_price) * 2), 2)
                    structure_desc = "Bearish (Trading in lower half of 15m range)"
                
                LATEST_STRUCTURE = {
                    "current_price": round(current_price, 2),
                    "trend": trend,
                    "swing_high": round(swing_high, 2),
                    "swing_low": round(swing_low, 2),
                    "sl": sl,
                    "tp": tp,
                    "structure_desc": structure_desc,
                    "updated_at": time.time()
                }
        except Exception as e:
            print(f"Structure engine update error: {e}")
            
        time.sleep(60)

threading.Thread(target=background_structure_engine, daemon=True).start()

# 3. TELEGRAM MESSAGING HELPER
def send_telegram_message(chat_id, message):
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

# 4. COMMAND LISTENER
def poll_telegram_commands():
    last_update_id = 0
    print("Listening for structure commands...")
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id}&timeout=30"
            res = requests.get(url, timeout=35).json()
            
            if "result" in res:
                for update in res["result"]:
                    last_update_id = update["update_id"] + 1
                    
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"].strip()
                        parts = text.split()
                        cmd = parts[0].lower()
                        
                        if cmd in ["/start", "start"]:
                            msg = (
                                "🤖 *Market Structure Engine Active*\n\n"
                                "Commands:\n"
                                "• `/entry <balance>` - Calculates structure setup\n"
                                "• `/gold` - Instant XAUUSD price\n\n"
                                "_Example:_ `/entry 100`"
                            )
                            send_telegram_message(chat_id, msg)
                            
                        elif cmd in ["/gold", "gold"]:
                            if LATEST_STRUCTURE["current_price"]:
                                send_telegram_message(chat_id, f"🪙 *XAUUSD Price:* `${LATEST_STRUCTURE['current_price']}`")
                            else:
                                send_telegram_message(chat_id, "⚠️ Structure calculation warming up...")
                                
                        elif cmd == "/entry":
                            if len(parts) < 2:
                                send_telegram_message(chat_id, "⚠️ *Format:* `/entry <balance>`\n*Example:* `/entry 100`")
                            else:
                                try:
                                    balance = float(parts[1])
                                    data = LATEST_STRUCTURE
                                    
                                    if data["current_price"]:
                                        risk_amount = balance * 0.01
                                        price_diff = abs(data['current_price'] - data['sl'])
                                        pips = price_diff * 10
                                        lot_size = round(max(0.01, risk_amount / (pips * 10.0)), 2) if pips > 0 else 0.01
                                        
                                        msg = (
                                            f"🚨 *STRUCTURE ORDER: {data['trend']} XAUUSD*\n\n"
                                            f"📍 *Entry Price:* `${data['current_price']}`\n"
                                            f"🛑 *Stop Loss:* `${data['sl']}`\n"
                                            f"🎯 *Take Profit:* `${data['tp']}`\n"
                                            f"📊 *Lot Size:* `{lot_size}`\n\n"
                                            f"🔍 *Structure:* {data['structure_desc']}\n"
                                            f"📈 *Swing High:* `${data['swing_high']}` | *Swing Low:* `${data['swing_low']}`"
                                        )
                                        send_telegram_message(chat_id, msg)
                                    else:
                                        send_telegram_message(chat_id, "⚠️ Background engine starting... try again in 10 seconds.")
                                except ValueError:
                                    send_telegram_message(chat_id, "⚠️ Enter a valid number for balance.")
                                    
        except Exception:
            time.sleep(2)
        time.sleep(1)

threading.Thread(target=poll_telegram_commands, daemon=True).start()

def main():
    while True:
        time.sleep(900)

if __name__ == "__main__":
    main()
