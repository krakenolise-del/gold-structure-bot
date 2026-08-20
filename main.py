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

    return None


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
    """Fetches technical analysis with automatic fallback and retry."""
    exchanges = ["TVC", "OANDA", "FOREXCOM"]
    
    for ex in exchanges:
        try:
            handler = TA_Handler(
                symbol="GOLD" if ex == "TVC" else "XAUUSD",
                screener="forex",
                exchange=ex,
                interval=interval,
                timeout=10
            )
            analysis = handler.get_analysis()
            if analysis and analysis.indicators:
                return analysis.indicators, analysis.summary
        except Exception:
            continue
            
    return None, None
            

def analyze_candle_precision():
    """Precise Candle Movement & Multi-Timeframe Engine."""
    curr_price = get_live_xauusd_price()
    m15_ind, m15_sum = get_ta_data(Interval.INTERVAL_15_MINUTES)
    m5_ind, m5_sum = get_ta_data(Interval.INTERVAL_5_MINUTES)

    # STRICT CHECK: If live data fails, abort signal instead of guessing
    if not curr_price or not m15_ind or not m5_ind:
        return None, "NO_DATA", "API Fetch Error", "Live feed timeout. Re-try in a few seconds.", "NEUTRAL", 3.0, 0, 0, 0

    # Candle Open vs Current Price
    m15_open = float(m15_ind.get("open", curr_price))
    m5_open = float(m5_ind.get("open", curr_price))

    # Dynamic Moving Averages
    ema10_m15 = float(m15_ind.get("EMA10", curr_price))
    ema20_m15 = float(m15_ind.get("EMA20", curr_price))
    ema10_m5 = float(m5_ind.get("EMA10", curr_price))
    
    rsi_m15 = float(m15_ind.get("RSI", 50.0))
    rsi_m5 = float(m5_ind.get("RSI", 50.0))
    atr = float(m15_ind.get("ATR", 3.0))
    if atr <= 0:
        atr = 3.0

    poc_price, vah_price, val_price = calculate_volume_profile()
    if not poc_price:
        poc_price, vah_price, val_price = curr_price, curr_price + 3.0, curr_price - 3.0

    buy_points, sell_points = 0, 0

    # 1. Active M15 Candle Direction (Heavy Weight +4)
    if curr_price < m15_open:
        sell_points += 4  # Bearish M15 candle currently forming
    else:
        buy_points += 4   # Bullish M15 candle currently forming

    # 2. Active M5 Micro-Candle Direction (Heavy Weight +3)
    if curr_price < m5_open:
        sell_points += 3  # Immediate M5 drop
    else:
        buy_points += 3   # Immediate M5 push

    # 3. Micro-EMA Alignment (M5 & M15 Fast Averages)
    if curr_price < ema10_m5:
        sell_points += 2
    else:
        buy_points += 2

    if curr_price < ema10_m15:
        sell_points += 2
    else:
        buy_points += 2

    # 4. Strict RSI Momentum Confirmation
    if rsi_m15 > 53 and rsi_m5 > 50:
        buy_points += 2
    elif rsi_m15 < 47 and rsi_m5 < 50:
        sell_points += 2

    # Determination of Bias
    if sell_points > buy_points:
        bias = "SELL"
        strategy_name = "Candle-Momentum Bearish Shift"
        detail = f"Active M15/M5 Red Candle | RSI M15: {rsi_m15:.1f} | M5 Open: ${m5_open:.2f}"
    elif buy_points > sell_points:
        bias = "BUY"
        strategy_name = "Candle-Momentum Bullish Expansion"
        detail = f"Active M15/M5 Green Candle | RSI M15: {rsi_m15:.1f} | M5 Open: ${m5_open:.2f}"
    else:
        bias = "NEUTRAL"
        strategy_name = "Indecisive Candle Action"
        detail = "Market consolidating between M5 and M15 levels."

    tv_consensus = m15_sum.get("RECOMMENDATION", "NEUTRAL") if m15_sum else "NEUTRAL"
    return curr_price, bias, strategy_name, detail, tv_consensus, atr, poc_price, vah_price, val_price


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 *Legend Of All Trade (Candle Precision Engine)*\n\n"
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
            bot.reply_to(message, "⚠️ Unable to fetch live price right now. Try again shortly.")
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
        price, trend, strategy_name, detail, tv_consensus, atr, poc, vah, val = analyze_candle_precision()

        if trend == "NO_DATA":
            bot.reply_to(message, "⚠️ *Market Data Fetch Timed Out.*\nPlease re-send `/entry` in 5 seconds to get an accurate reading.", parse_mode="Markdown")
            return

        if trend == "NEUTRAL":
            bot.reply_to(message, "⚠️ *Market is currently indecisive.* No clear M5/M15 candle direction. Hold trades.", parse_mode="Markdown")
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
            f"🏛 *CANDLE PRECISION EXECUTION*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• *Live Spot Price:* `${price:.2f}`\n\n"
            f"📊 *Volume Profile & Structure:*\n"
            f"• *Point of Control (POC):* `${poc:.2f}`\n"
            f"• *Value Area High (VAH):* `${vah:.2f}`\n"
            f"• *Value Area Low (VAL):* `${val:.2f}`\n\n"
            f"📐 *Real-Time Candle Analysis:*\n"
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
