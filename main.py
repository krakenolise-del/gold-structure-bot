import os
import requests
import numpy as np
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

    return 4523.50


def calculate_volume_profile(num_bars=40, num_bins=15):
    """Calculates Fixed Range Volume Profile (POC, VAH, VAL)."""
    try:
        url = "https://stooq.com/q/d/l/?s=xauusd&i=5"
        df = pd.read_csv(url).tail(num_bars)

        if df.empty or 'High' not in df.columns:
            return None, None, None

        highs = df['High'].values
        lows = df['Low'].values
        volumes = df['Volume'].values if 'Volume' in df.columns else np.ones(len(highs))

        min_price, max_price = np.min(lows), np.max(highs)
        bins = np.linspace(min_price, max_price, num_bins)
        vol_dist = np.zeros(num_bins - 1)

        for i in range(len(highs)):
            bar_bins = np.where((bins >= lows[i]) & (bins <= highs[i]))[0]
            if len(bar_bins) > 0:
                vol_per_bin = volumes[i] / len(bar_bins)
                for b_idx in bar_bins:
                    if b_idx < len(vol_dist):
                        vol_dist[b_idx] += vol_per_bin

        poc_idx = np.argmax(vol_dist)
        poc_price = round((bins[poc_idx] + bins[poc_idx + 1]) / 2, 2)

        total_vol = np.sum(vol_dist)
        target_vol = total_vol * 0.70
        sorted_indices = np.argsort(vol_dist)[::-1]

        accum_vol, va_bins = 0, []
        for idx in sorted_indices:
            accum_vol += vol_dist[idx]
            va_bins.append(idx)
            if accum_vol >= target_vol:
                break

        val_price = round(bins[np.min(va_bins)], 2)
        vah_price = round(bins[np.max(va_bins) + 1], 2)

        return poc_price, vah_price, val_price
    except Exception:
        return None, None, None


def get_ta_data(interval):
    try:
        handler = TA_Handler(symbol="XAUUSD", screener="forex", exchange="OANDA", interval=interval)
        analysis = handler.get_analysis()
        return analysis.indicators, analysis.summary
    except Exception:
        return {}, {}


def analyze_aggressive_m15():
    """Aggressive Execution Engine with Micro-Shift Detection."""
    curr_price = get_live_xauusd_price()

    m15_ind, m15_sum = get_ta_data(Interval.INTERVAL_15_MINUTES)

    # Short-term EMA for immediate momentum detection
    ema10 = float(m15_ind.get("EMA10", curr_price))
    ema20 = float(m15_ind.get("EMA20", curr_price))
    ema50 = float(m15_ind.get("EMA50", curr_price))
    rsi = float(m15_ind.get("RSI", 50))
    atr = float(m15_ind.get("ATR", 3.0))
    if atr <= 0:
        atr = 3.0

    poc_price, vah_price, val_price = calculate_volume_profile()
    if not poc_price:
        poc_price, vah_price, val_price = curr_price, curr_price + 3.0, curr_price - 3.0

    buy_points, sell_points = 0, 0

    # 1. Immediate Micro-Shift Filter (Heavy Weight)
    if curr_price < ema10:
        sell_points += 3
    else:
        buy_points += 3

    # 2. Medium Trend Filter
    if curr_price >= ema20:
        buy_points += 2
    else:
        sell_points += 2

    # 3. Macro Trend Filter
    if curr_price > ema50:
        buy_points += 1
    else:
        sell_points += 1

    # 4. Momentum Oscillator Filter (RSI Buffer)
    if rsi >= 52:
        buy_points += 2
    elif rsi <= 48:
        sell_points += 2

    # 5. Volume Profile Structure
    if curr_price >= poc_price:
        buy_points += 1
    else:
        sell_points += 1

    # Absolute Buy/Sell Split
    if buy_points > sell_points:
        bias = "BUY"
        strategy_name = "Aggressive M15 Bullish Expansion"
        detail = f"Price above Fast EMA Structure | RSI: {rsi:.1f} | ATR: ${atr:.2f}"
    else:
        bias = "SELL"
        strategy_name = "Aggressive M15 Bearish Micro-Shift"
        detail = f"Price breaking below Fast EMA | RSI: {rsi:.1f} | ATR: ${atr:.2f}"

    tv_consensus = m15_sum.get("RECOMMENDATION", "NEUTRAL")
    return curr_price, bias, strategy_name, detail, tv_consensus, atr, poc_price, vah_price, val_price


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 *Legend Of All Trade (Aggressive Engine)*\n\n"
        "Commands:\n"
        "• `/gold` — Live Spot Price\n"
        "• `/entry <balance>` — Immediate Active Buy/Sell Trade"
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
            bot.reply_to(message, "⚠️ Provide balance.\n*Example:* `/entry 10`", parse_mode="Markdown")
            return

        balance = float(args[1])
        price, trend, strategy_name, detail, tv_consensus, atr, poc, vah, val = analyze_aggressive_m15()

        sl_dist = round(atr * 1.2, 2)
        tp_dist = round(sl_dist * 2.2, 2)

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
            f"🏛 *AGGRESSIVE EXECUTION (NO WAIT)*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• *Live Spot Price:* `${price:.2f}`\n\n"
            f"📊 *Volume Profile & Structure:*\n"
            f"• *Point of Control (POC):* `${poc:.2f}`\n"
            f"• *Value Area High (VAH):* `${vah:.2f}`\n"
            f"• *Value Area Low (VAL):* `${val:.2f}`\n\n"
            f"📐 *Market Analysis:*\n"
            f"• *Pattern:* `{strategy_name}`\n"
            f"• *Details:* _{detail}_\n"
            f"• *Consensus:* `{tv_consensus}`\n\n"
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
    
