import os
import time
import requests
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telebot import TeleBot

# Telegram Bot Token
BOT_TOKEN = os.environ.get("BOT_TOKEN")
bot = TeleBot(BOT_TOKEN)

# Global Storage for Market Structure Engine
LATEST_STRUCTURE = {}

# Simple Web Server to Keep Render Web Service Alive
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Active")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

Thread(target=run_web_server, daemon=True).start()


# CONTINUOUS BACKGROUND STRUCTURE ENGINE
def background_structure_engine():
    global LATEST_STRUCTURE
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url = "https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=15m&range=2d"
    
    while True:
        try:
            r = requests.get(url, headers=headers, timeout=10).json()
            chart = r.get('chart', {}).get('result', [])[0]
            indicators = chart.get('indicators', {}).get('quote', [])[0]
            
            highs = indicators.get('high', [])
            lows = indicators.get('low', [])
            closes = indicators.get('close', [])
            
            valid_candles = [
                (h, l, c) for h, l, c in zip(highs, lows, closes) 
                if h is not None and l is not None and c is not None
            ]
            
            if len(valid_candles) >= 20:
                recent_highs = [x[0] for x in valid_candles[-20:]]
                recent_lows = [x[1] for x in valid_candles[-20:]]
                current_price = valid_candles[-1][2]
                
                swing_high = max(recent_highs)
                swing_low = min(recent_lows)
                mid_point = (swing_high + swing_low) / 2
                
                if current_price > mid_point:
                    trend = "BUY"
                    sl = round(swing_low - 0.50, 2)
                    tp = round(current_price + ((current_price - sl) * 2), 2)
                    structure_desc = "Bullish (Upper half of 15m structure)"
                else:
                    trend = "SELL"
                    sl = round(swing_high + 0.50, 2)
                    tp = round(current_price - ((sl - current_price) * 2), 2)
                    structure_desc = "Bearish (Lower half of 15m structure)"
                
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
            
        time.sleep(30)

Thread(target=background_structure_engine, daemon=True).start()


# TELEGRAM BOT COMMAND HANDLERS
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 *Market Structure Engine Active*\n\n"
        "Commands:\n"
        "• `/entry <balance>` - Calculates structure setup\n"
        "• `/gold` - Instant XAUUSD price\n\n"
        "_Example:_ `/entry 100`"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['gold'])
def get_gold_price(message):
    if LATEST_STRUCTURE and "current_price" in LATEST_STRUCTURE:
        price = LATEST_STRUCTURE["current_price"]
        bot.reply_to(message, f"🌕 *XAUUSD Price:* ${price}", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ Structure calculation warming up... Send /gold again in 15 seconds.")

@bot.message_handler(commands=['entry'])
def calculate_entry(message):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Please provide your account balance.\n*Example:* `/entry 100`", parse_mode="Markdown")
            return
            
        balance = float(args[1])
        
        if not LATEST_STRUCTURE or "current_price" not in LATEST_STRUCTURE:
            bot.reply_to(message, "⚠️ Market structure engine is loading... Try again in a few seconds.")
            return

        price = LATEST_STRUCTURE["current_price"]
        trend = LATEST_STRUCTURE["trend"]
        sl = LATEST_STRUCTURE["sl"]
        tp = LATEST_STRUCTURE["tp"]
        desc = LATEST_STRUCTURE["structure_desc"]

        # Risk 2% of total balance
        risk_amount = balance * 0.02
        sl_distance = abs(price - sl)
        
        if sl_distance == 0:
            sl_distance = 1.0

        # Lot size formula for Gold (1 Standard Lot = $100 per $1 move)
        lot_size = round(risk_amount / (sl_distance * 100), 2)
        if lot_size < 0.01:
            lot_size = 0.01

        response = (
            f"📊 *XAUUSD STRUCTURE SETUP*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• *Current Price:* ${price}\n"
            f"• *Bias:* {trend} ({desc})\n\n"
            f"🎯 *Trade Parameters:*\n"
            f"• *Signal:* {trend}\n"
            f"• *Entry:* ${price}\n"
            f"• *Stop Loss (SL):* ${sl}\n"
            f"• *Take Profit (TP):* ${tp}\n\n"
            f"🛡 *Risk Management (2% Risk):*\n"
            f"• *Account Balance:* ${balance:.2f}\n"
            f"• *Max Risk:* ${risk_amount:.2f}\n"
            f"• *Recommended Lot:* `{lot_size}` Lot\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        bot.reply_to(message, response, parse_mode="Markdown")

    except ValueError:
        bot.reply_to(message, "⚠️ Invalid balance format. Send a number like `/entry 100`.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error processing setup: {e}")


# START TELEGRAM BOT LOOP
if __name__ == "__main__":
    bot.infinity_polling()
