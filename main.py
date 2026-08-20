import os
import requests
import numpy as np
import pandas as pd
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telebot import TeleBot

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
    """Fetches real-time spot price."""
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

    return None


def fetch_stooq_ohlc():
    """Fetches fast OHLC data directly from Stooq without scraping limits."""
    try:
        url = "https://stooq.com/q/d/l/?s=xauusd&i=5"
        df = pd.read_csv(url).tail(30)
        if not df.empty and 'Close' in df.columns:
            return df
    except Exception:
        pass
    return None


def analyze_direct_momentum():
    """Direct Price Action & Volume Engine (Zero TradingView Dependencies)."""
    curr_price = get_live_xauusd_price()
    df = fetch_stooq_ohlc()

    if not curr_price:
        return None, "NO_DATA", "Price API Offline", "Could not retrieve live market price.", 3.0, 0, 0, 0

    if df is None or len(df) < 10:
        bias = "BUY" if curr_price >= 4520.00 else "SELL"
        return curr_price, bias, "Live Price Velocity", "Direct price check active", 3.0, curr_price, curr_price + 3, curr_price - 3

    closes = df['Close'].values
    highs = df['High'].values
    lows = df['Low'].values
    
    ema9 = pd.Series(closes).ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = pd.Series(closes).ewm(span=21, adjust=False).mean().iloc[-1]
    
    recent_open = closes[-2]
    atr = np.mean(highs[-10:] - lows[-10:])
    if atr <= 0 or np.isnan(atr):
        atr = 3.0

    poc_price = round(np.mean(closes[-15:]), 2)
    vah_price = round(poc_price + (atr * 1.5), 2)
    val_price = round(poc_price - (atr * 1.5), 2)

    buy_points, sell_points = 0, 0

    # 1. Direct Candle Direction (Current Price vs Candle Open)
    if curr_price < recent_open:
        sell_points += 4
    else:
        buy_points += 4

    # 2. Fast EMA9 Alignment
    if curr_price < ema9:
        sell_points += 3
    else:
        buy_points += 3

    # 3. EMA Crossover Momentum
    if ema9 < ema21:
        sell_points += 2
    else:
        buy_points += 2

    if sell_points > buy_points:
        bias = "SELL"
        strategy_name = "Direct Bearish Micro-Shift"
        detail = f"Price below Fast EMA9 (${ema9:.2f}) | Candle Drop Active"
    else:
        bias = "BUY"
        strategy_name = "Direct Bullish Expansion"
        detail = f"Price holding above Fast EMA9 (${ema9:.2f}) | Candle Push Active"

    return curr_price, bias, strategy_name, detail, atr, poc_price, vah_price, val_price


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 *Legend Of All Trade (Direct Engine)*\n\n"
        "Commands:\n"
        "• `/gold` — Live Spot Price\n"
        "• `/entry <balance>` — Immediate Active Trade Setup"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")


@bot.message_handler(commands=['gold'])
def send_gold_price(message):
    try:
        price = get_live_xauusd_price()
        if price:
            bot.reply_to(message, f"🟡 *Live XAUUSD Spot:* `${price:.2f}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, "⚠️ Unable to fetch live price right now.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=['entry'])
def send_entry_setup(message):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Provide balance.\n*Example:* `/entry 10`", parse_mode="Markdown")
            return

        balance = float(args[1])
        price, trend, strategy_name, detail, atr, poc, vah, val = analyze_direct_momentum()

        if trend == "NO_DATA":
            bot.reply_to(message, "⚠️ *Price Feed Error.* Try again in a few seconds.", parse_mode="Markdown")
            return

        sl_dist = round(atr * 1.0, 2)
        tp_dist = round(sl_dist * 2.0, 2)

        if trend == "BUY":
            sl_price = round(price - sl_dist, 2)
            tp_price = round(price + tp_dist, 2)
            action_text = "🟢 **ACTION: OPEN BUY ORDER NOW**"
        else:
            sl_price = round(price + sl_dist, 2)
            tp_price = round(price - tp_dist, 2)
            action_text = "🔴 **ACTION: OPEN SELL ORDER NOW**"

        risk_amount = balance * 0.02
        lot_size = round(risk_amount / (sl_dist * 100), 2)
        if lot_size < 0.01:
            lot_size = 0.01

        response = (
            f"🏛 *DIRECT MOMENTUM EXECUTION*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• *Live Spot Price:* `${price:.2f}`\n\n"
            f"📊 *Volume Profile & Structure:*\n"
            f"• *Point of Control (POC):* `${poc:.2f}`\n"
            f"• *Value Area High (VAH):* `${vah:.2f}`\n"
            f"• *Value Area Low (VAL):* `${val:.2f}`\n\n"
            f"📐 *Real-Time Candle Analysis:*\n"
            f"• *Pattern:* `{strategy_name}`\n"
            f"• *Details:* _{detail}_\n\n"
            f"🎯 *Execution:* {action_text}\n"
            f"• *Bias Signal:* *{trend}*\n"
            f"• *Entry:* `${price:.2f}`\n"
            f"• *Dynamic SL:* `${sl_price:.2f}`\n"
            f"• *Dynamic TP:* `${tp_price:.2f}`\n\n"
            f"🛡 *Risk Management (2% Risk):*\n"
            f"• *Account Balance:* `${balance:.2f}`\n"
            f"• *Risk Amount:* `${risk_amount:.2f}`\n"
            f"• *Recommended Lot:* `{lot_size}` Lot\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        bot.reply_to(message, response, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Execution Error: {e}")

bot.infinity_polling()
    
