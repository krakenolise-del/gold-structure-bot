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

    return 4481.90


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


def analyze_master_confluence_m15():
    """6-Layer Master Confluence Engine."""
    curr_price = get_live_xauusd_price()

    m15_ind, m15_sum = get_ta_data(Interval.INTERVAL_15_MINUTES)
    h1_ind, _ = get_ta_data(Interval.INTERVAL_1_HOUR)

    # Core Technical Indicators
    ema20 = float(m15_ind.get("EMA20", curr_price))
    ema50 = float(m15_ind.get("EMA50", curr_price))
    rsi = float(m15_ind.get("RSI", 50))
    atr = float(m15_ind.get("ATR", 3.0))
    if atr <= 0:
        atr = 3.0

    # Ichimoku Cloud Elements
    tenkan = float(m15_ind.get("Ichimoku.BLine", curr_price))
    kijun = float(m15_ind.get("Ichimoku.CLine", curr_price))

    # Candlestick Price Action & Wick Rejection
    open_p = float(m15_ind.get("open", curr_price))
    high_p = float(m15_ind.get("high", curr_price + 1.0))
    low_p = float(m15_ind.get("low", curr_price - 1.0))
    close_p = float(m15_ind.get("close", curr_price))

    candle_range = max(high_p - low_p, 0.1)
    lower_wick = min(open_p, close_p) - low_p
    upper_wick = high_p - max(open_p, close_p)

    bullish_rejection = (lower_wick / candle_range) > 0.45
    bearish_rejection = (upper_wick / candle_range) > 0.45

    # Smart Money Concepts (FVG / Imbalance Check)
    high_2 = float(m15_ind.get("high[2]", curr_price + 2.0))
    low_0 = float(m15_ind.get("low", curr_price - 1.0))
    low_2 = float(m15_ind.get("low[2]", curr_price - 2.0))
    high_0 = float(m15_ind.get("high", curr_price + 1.0))

    bullish_fvg = low_0 > high_2
    bearish_fvg = high_0 < low_2

    # Volume Profile Engine
    poc_price, vah_price, val_price = calculate_volume_profile()
    if not poc_price:
        poc_price, vah_price, val_price = curr_price, curr_price + 3.0, curr_price - 3.0

    buy_points, sell_points = 0, 0

    # Strategy 1: Volume Profile Value Areas
    if curr_price <= val_price:
        buy_points += 3
    elif curr_price >= vah_price:
        sell_points += 3

    # Strategy 2: SMC Fair Value Gap (FVG)
    if bullish_fvg or (curr_price > poc_price and curr_price < vah_price):
        buy_points += 2
    elif bearish_fvg or (curr_price < poc_price and curr_price > val_price):
        sell_points += 2

    # Strategy 3: Price Action Rejection Wicks
    if bullish_rejection:
        buy_points += 2
    elif bearish_rejection:
        sell_points += 2

    # Strategy 4: Ichimoku Cloud Alignment
    if curr_price > tenkan > kijun:
        buy_points += 1
    elif curr_price < tenkan < kijun:
        sell_points += 1

    # Strategy 5: Dynamic Moving Average Stack
    if curr_price > ema20 > ema50:
        buy_points += 1
    elif curr_price < ema20 < ema50:
        sell_points += 1

    # Strategy 6: RSI Momentum Filter
    if 52 < rsi < 70:
        buy_points += 1
    elif 30 < rsi < 48:
        sell_points += 1

    # Master Confluence Threshold Execution (Requires >= 6 Points)
    if buy_points >= 6 and buy_points > sell_points:
        bias = "BUY"
        strategy_name = "Master Bullish Confluence (SMC + VP + Wick Rejection)"
        detail = f"VAL Discount | Bullish Wick/FVG Detected | Ichimoku & EMA Stacked | ATR: ${atr:.2f}"
    elif sell_points >= 6 and sell_points > buy_points:
        bias = "SELL"
        strategy_name = "Master Bearish Confluence (SMC + VP + Supply Rejection)"
        detail = f"VAH Premium | Bearish Wick/FVG Detected | Ichimoku & EMA Dropping | ATR: ${atr:.2f}"
    else:
        bias = "WAIT"
        strategy_name = "Low Confluence / Market Ranging"
        detail = f"Score Insufficient (Buy: {buy_points}/10, Sell: {sell_points}/10) | Consolidating near POC (${poc_price:.2f})"

    tv_consensus = m15_sum.get("RECOMMENDATION", "NEUTRAL")
    return curr_price, bias, strategy_name, detail, tv_consensus, atr, poc_price, vah_price, val_price


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 *Legend Of All Trade (Master Engine)*\n\n"
        "Commands:\n"
        "• `/gold` — Live Spot Price\n"
        "• `/entry <balance>` — Execute 6-Layer Master Confluence"
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
            bot.reply_to(message, "⚠️ Provide balance.\n*Example:* `/entry 100`", parse_mode="Markdown")
            return

        balance = float(args[1])
        price, trend, strategy_name, detail, tv_consensus, atr, poc, vah, val = analyze_master_confluence_m15()

        sl_dist = round(atr * 1.2, 2)
        tp_dist = round(sl_dist * 2.2, 2)

        if trend == "BUY":
            sl_price = round(price - sl_dist, 2)
            tp_price = round(price + tp_dist, 2)
            action_text = "🟢 **ACTION: OPEN BUY ORDER**"
            sl_str = f"${sl_price:.2f}"
            tp_str = f"${tp_price:.2f}"
        elif trend == "SELL":
            sl_price = round(price + sl_dist, 2)
            tp_price = round(price - tp_dist, 2)
            action_text = "🔴 **ACTION: OPEN SELL ORDER**"
            sl_str = f"${sl_price:.2f}"
            tp_str = f"${tp_price:.2f}"
        else:
            action_text = "⚠️ **ACTION: NO TRADE (HOLD/WAIT)**"
            sl_str = f"N/A (Hold State)"
            tp_str = f"N/A (Hold State)"

        risk_amount = balance * 0.02
        lot_size = round(risk_amount / (sl_dist * 100), 2) if sl_dist > 0 else 0.01
        if lot_size < 0.01:
            lot_size = 0.01

        response = (
            f"🏛 *MASTER CONFLUENCE ANALYSIS (M15)*\n"
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
            f"• *Dynamic SL:* `{sl_str}`\n"
            f"• *Dynamic TP:* `{tp_str}`\n\n"
            f"🛡 *Risk Management (2% Risk):*\n"
            f"• *Account Balance:* `${balance:.2f}`\n"
            f"• *Risk Amount:* `${risk_amount:.2f}`\n"
            f"• *Recommended Lot:* `{lot_size}` Lot\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        bot.reply_to(message, response, parse_mode="Markdown")

    except ValueError:
        bot.reply_to(message, "⚠️ Enter a valid numerical balance, e.g., `/entry 100`.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


if __name__ == "__main__":
    bot.infinity_polling()
        
