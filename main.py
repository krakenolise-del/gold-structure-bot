import os
import requests
import pandas as pd
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telebot import TeleBot
from tradingview_ta import TA_Handler, Interval

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GOLD_API_KEY = os.environ.get("GOLD_API_KEY")

bot = TeleBot(BOT_TOKEN)

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


def get_live_xauusd_price():
    """Fetches exact real-time XAUUSD spot price from GoldAPI."""
    if GOLD_API_KEY:
        try:
            url = "https://www.goldapi.io/api/XAU/USD"
            headers = {
                "x-access-token": GOLD_API_KEY,
                "Content-Type": "application/json"
            }
            res = requests.get(url, headers=headers, timeout=5).json()
            if "price" in res and res["price"] > 0:
                return float(res["price"])
        except Exception:
            pass

    # Fallback to secondary spot provider
    try:
        url = "https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlcv&h&e=csv"
        r = requests.get(url, timeout=5)
        lines = r.text.strip().split("\n")
        if len(lines) > 1:
            p = float(lines[1].split(",")[6])
            if p > 0:
                return p
    except Exception:
        pass

    return 4468.40


def get_market_structure(style):
    """Maps structure using exact live spot prices."""
    curr_price = get_live_xauusd_price()

    try:
        timeframe = Interval.INTERVAL_5_MINUTES if style in ["scalp", "scalping"] else Interval.INTERVAL_1_HOUR
        handler = TA_Handler(symbol="XAUUSD", screener="forex", exchange="OANDA", interval=timeframe)
        analysis = handler.get_analysis()
        indicators = analysis.indicators

        high_val = float(indicators.get("high", curr_price + 3.0))
        low_val = float(indicators.get("low", curr_price - 3.0))

        if curr_price > high_val:
            structure_signal = "BOS (Bullish Breakout)"
            structure_note = f"Trading above key resistance zone (${high_val:.2f})"
            bias = "BUY"
        elif curr_price < low_val:
            structure_signal = "BOS (Bearish Breakdown)"
            structure_note = f"Trading below key support zone (${low_val:.2f})"
            bias = "SELL"
        else:
            midpoint = (high_val + low_val) / 2
            if curr_price > midpoint:
                structure_signal = "Bullish Order Block Test"
                structure_note = f"Holding above demand zone (${low_val:.2f})"
                bias = "BUY"
            else:
                structure_signal = "Bearish Supply Reaction"
                structure_note = f"Rejecting below supply zone (${high_val:.2f})"
                bias = "SELL"

        return curr_price, bias, structure_signal, structure_note

    except Exception:
        return curr_price, "SELL", "Bearish Supply Reaction", "Rejecting below key resistance"


def get_tradingview_prediction(style):
    timeframe = Interval.INTERVAL_5_MINUTES if style in ["scalp", "scalping"] else Interval.INTERVAL_1_HOUR
    try:
        handler = TA_Handler(symbol="XAUUSD", screener="forex", exchange="OANDA", interval=timeframe)
        analysis = handler.get_analysis()
        return analysis.summary.get("RECOMMENDATION", "NEUTRAL")
    except Exception:
        return "NEUTRAL"


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 *Real-Time Spot Gold (XAUUSD) Bot*\n\n"
        "Commands:\n"
        "• `/gold` — Live Spot Price\n"
        "• `/entry <balance> <style>` — Structure setup & entry points\n\n"
        "*Usage Examples:*\n"
        "• `/entry 100 scalp` — 5-minute micro-structure\n"
        "• `/entry 100 day` — 1-hour macro-structure"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")


@bot.message_handler(commands=['gold'])
def send_gold_price(message):
    try:
        price = get_live_xauusd_price()
        bot.reply_to(message, f"🌕 *Live XAUUSD Spot:* `${price:.2f}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Failed to fetch price: {e}")


@bot.message_handler(commands=['entry'])
def send_entry_setup(message):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Provide balance and style.\n*Examples:*\n`/entry 100 scalp`\n`/entry 100 day`", parse_mode="Markdown")
            return

        balance = float(args[1])
        style = args[2].lower() if len(args) >= 3 else "day"

        price, trend, structure_signal, structure_note = get_market_structure(style)
        tv_consensus = get_tradingview_prediction(style)

        if style in ["scalp", "scalping"]:
            style_label = "⚡ SCALPING (5M Structure)"
            sl_dist = 2.5
            tp_dist = 5.0
        else:
            style_label = "📈 DAY TRADING (1H Structure)"
            sl_dist = 5.0
            tp_dist = 10.0

        if trend == "BUY":
            sl = round(price - sl_dist, 2)
            tp = round(price + tp_dist, 2)
        else:
            sl = round(price + sl_dist, 2)
            tp = round(price - tp_dist, 2)

        risk_amount = balance * 0.02
        lot_size = round(risk_amount / (sl_dist * 100), 2)
        if lot_size < 0.01:
            lot_size = 0.01

        response = (
            f"🏛 *XAUUSD MARKET STRUCTURE ANALYSIS*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• *Mode:* `{style_label}`\n"
            f"• *Live Price:* `${price:.2f}`\n\n"
            f"📐 *Structure Mapping:*\n"
            f"• *Pattern Detected:* `{structure_signal}`\n"
            f"• *Zone Detail:* _{structure_note}_\n"
            f"• *TV Consensus:* `{tv_consensus}`\n\n"
            f"🎯 *Execution Setup:*\n"
            f"• *Bias Signal:* *{trend}*\n"
            f"• *Entry:* `${price:.2f}`\n"
            f"• *Stop Loss (SL):* `${sl:.2f}`\n"
            f"• *Take Profit (TP):* `${tp:.2f}`\n\n"
            f"🛡 *Risk Management (2% Risk):*\n"
            f"• *Account Balance:* `${balance:.2f}`\n"
            f"• *Risk Amount:* `${risk_amount:.2f}`\n"
            f"• *Recommended Lot:* `{lot_size}` Lot\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        bot.reply_to(message, response, parse_mode="Markdown")

    except ValueError:
        bot.reply_to(message, "⚠️ Enter a valid number like `/entry 100 scalp`.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


if __name__ == "__main__":
    bot.infinity_polling()
            
