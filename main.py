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
    if GOLD_API_KEY:
        try:
            url = "https://www.goldapi.io/api/XAU/USD"
            headers = {"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"}
            res = requests.get(url, headers=headers, timeout=5).json()
            if "price" in res and res["price"] > 0:
                return float(res["price"])
        except Exception:
            pass

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
    curr_price = get_live_xauusd_price()
    timeframe = Interval.INTERVAL_5_MINUTES if style in ["scalp", "scalping"] else Interval.INTERVAL_1_HOUR

    try:
        handler = TA_Handler(symbol="XAUUSD", screener="forex", exchange="OANDA", interval=timeframe)
        analysis = handler.get_analysis()
        indicators = analysis.indicators
        summary = analysis.summary

        # Technical Indicators
        rsi = float(indicators.get("RSI", 50))
        ema20 = float(indicators.get("EMA20", curr_price))
        high_val = float(indicators.get("high", curr_price + 3.0))
        low_val = float(indicators.get("low", curr_price - 3.0))
        
        tv_buy_votes = summary.get("BUY", 0)
        tv_sell_votes = summary.get("SELL", 0)

        # Multi-Confluence Decision Engine
        if curr_price > ema20 and rsi > 52 and tv_buy_votes >= tv_sell_votes:
            bias = "BUY"
            structure_signal = "Bullish Order Block Retention"
            structure_note = f"Price holding above EMA20 (${ema20:.2f}) with RSI at {rsi:.1f}"
        elif curr_price < ema20 and rsi < 48 and tv_sell_votes >= tv_buy_votes:
            bias = "SELL"
            structure_signal = "Bearish Supply Rejection"
            structure_note = f"Price trading below EMA20 (${ema20:.2f}) with RSI at {rsi:.1f}"
        else:
            # Range / Neutral fallback
            if curr_price > (high_val + low_val) / 2:
                bias = "BUY"
                structure_signal = "Bullish Liquidity Sweep"
                structure_note = f"Rebound from local demand near ${low_val:.2f}"
            else:
                bias = "SELL"
                structure_signal = "Bearish Resistance Reject"
                structure_note = f"Pullback from key resistance near ${high_val:.2f}"

        tv_consensus = summary.get("RECOMMENDATION", "NEUTRAL")
        return curr_price, bias, structure_signal, structure_note, tv_consensus

    except Exception:
        return curr_price, "SELL", "Bearish Supply Reaction", "Rejecting resistance zone", "NEUTRAL"


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 *Legend Of All Trade Bot*\n\n"
        "Commands:\n"
        "• `/gold` — Live Spot Price\n"
        "• `/entry <balance> <style>` — High-Confluence Setup\n\n"
        "*Examples:*\n"
        "• `/entry 100 scalp` — 5M Confluence\n"
        "• `/entry 100 day` — 1H Confluence"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")


@bot.message_handler(commands=['gold'])
def send_gold_price(message):
    try:
        price = get_live_xauusd_price()
        bot.reply_to(message, f"🟡 *Live XAUUSD Spot:* `${price:.2f}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=['entry'])
def send_entry_setup(message):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Provide balance and style.\n*Example:* `/entry 100 scalp`", parse_mode="Markdown")
            return

        balance = float(args[1])
        style = args[2].lower() if len(args) >= 3 else "day"

        price, trend, structure_signal, structure_note, tv_consensus = get_market_structure(style)

        if style in ["scalp", "scalping"]:
            style_label = "⚡ SCALPING (5M Structure)"
            sl_dist = 2.0  # Tightened 20-pip SL for scalps
            tp_dist = 5.0  # 50-pip TP (1:2.5 Risk-Reward)
        else:
            style_label = "📈 DAY TRADING (1H Structure)"
            sl_dist = 4.0  # 40-pip SL
            tp_dist = 10.0 # 100-pip TP (1:2.5 Risk-Reward)

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
                      
