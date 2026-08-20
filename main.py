import os
import requests
import numpy as np
import pandas as pd
from datetime import datetime
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


def fetch_stooq_ohlc(interval="15"):
    """Fetches OHLC data for SMC calculations."""
    try:
        url = f"https://stooq.com/q/d/l/?s=xauusd&i={interval}"
        df = pd.read_csv(url).tail(40)
        if not df.empty and 'Close' in df.columns:
            return df
    except Exception:
        pass
    return None


def detect_fvg(df):
    """Detects 3-candle Fair Value Gaps (FVG) on M15."""
    if df is None or len(df) < 3:
        return "NONE"
    
    highs = df['High'].values
    lows = df['Low'].values
    
    # Bullish FVG: Candle 1 High < Candle 3 Low
    if lows[-1] > highs[-3]:
        return "BULLISH_FVG"
    # Bearish FVG: Candle 1 Low > Candle 3 High
    elif highs[-1] < lows[-3]:
        return "BEARISH_FVG"
        
    return "NONE"


def detect_liquidity_sweep(df, curr_price):
    """Detects Buyside (BSL) or Sellside (SSL) Liquidity Sweeps."""
    if df is None or len(df) < 15:
        return "NONE"
    
    recent_high = np.max(df['High'].values[-15:-2])
    recent_low = np.min(df['Low'].values[-15:-2])
    
    # Sweep of Highs (Fakeout UP, then rejection)
    if df['High'].values[-1] > recent_high and curr_price < recent_high:
        return "BSL_SWEEP"  # Liquidity grabbed at top -> Strong SELL signal
    # Sweep of Lows (Fakeout DOWN, then rejection)
    elif df['Low'].values[-1] < recent_low and curr_price > recent_low:
        return "SSL_SWEEP"  # Liquidity grabbed at bottom -> Strong BUY signal
        
    return "NONE"


def analyze_smc_engine():
    """Smart Money Concepts (SMC) Execution Engine."""
    curr_price = get_live_xauusd_price()
    df_m15 = fetch_stooq_ohlc(interval="15")
    df_h1 = fetch_stooq_ohlc(interval="60")

    if not curr_price:
        return None, "NO_DATA", "Price API Offline", "Could not retrieve live price.", 3.0, 0, 0, 0, "NONE"

    if df_m15 is None or len(df_m15) < 10:
        bias = "BUY" if curr_price >= 4520.00 else "SELL"
        return curr_price, bias, "Fallback Momentum", "Direct price check active", 3.0, curr_price, curr_price + 3, curr_price - 3, "NONE"

    # --- 1. SMC MACRO TREND (H1 Market Structure) ---
    h1_closes = df_h1['Close'].values if df_h1 is not None and len(df_h1) >= 20 else df_m15['Close'].values
    h1_ema = pd.Series(h1_closes).ewm(span=20, adjust=False).mean().iloc[-1]
    h1_bias = "BULLISH" if curr_price >= h1_ema else "BEARISH"

    # --- 2. SMC M15 INDICATORS ---
    fvg_status = detect_fvg(df_m15)
    sweep_status = detect_liquidity_sweep(df_m15, curr_price)
    
    m15_highs = df_m15['High'].values
    m15_lows = df_m15['Low'].values
    m15_closes = df_m15['Close'].values

    atr = np.mean(m15_highs[-10:] - m15_lows[-10:])
    if atr <= 0 or np.isnan(atr):
        atr = 3.0

    poc_price = round(np.mean(m15_closes[-15:]), 2)
    order_block_high = round(np.max(m15_highs[-5:]), 2)
    order_block_low = round(np.min(m15_lows[-5:]), 2)

    smc_score = 0

    # SMC Score logic
    if sweep_status == "SSL_SWEEP":
        smc_score += 4  # Strong institutional buy footprint
    elif sweep_status == "BSL_SWEEP":
        smc_score -= 4  # Strong institutional sell footprint

    if fvg_status == "BULLISH_FVG":
        smc_score += 3
    elif fvg_status == "BEARISH_FVG":
        smc_score -= 3

    if h1_bias == "BULLISH":
        smc_score += 2
    else:
        smc_score -= 2

    # --- 3. CONFLUENCE BIAS ---
    if smc_score >= 3:
        bias = "BUY"
        strategy_name = "SMC Institutional Expansion (BUY)"
        detail = f"H1 {h1_bias} | FVG: {fvg_status} | Sweep: {sweep_status}"
    elif smc_score <= -3:
        bias = "SELL"
        strategy_name = "SMC Institutional Displacement (SELL)"
        detail = f"H1 {h1_bias} | FVG: {fvg_status} | Sweep: {sweep_status}"
    else:
        bias = "NEUTRAL"
        strategy_name = "SMC Consolidation / Inducement"
        detail = "No clear institutional order flow. Waiting for Liquidity Sweep or FVG."

    return curr_price, bias, strategy_name, detail, atr, poc_price, order_block_high, order_block_low, fvg_status


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🏛 *Legend Of All Trade (SMC Smart Money Engine)*\n\n"
        "Commands:\n"
        "• `/gold` — Live Spot Price\n"
        "• `/entry <balance>` — SMC Institutional Entry Setup"
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
        price, trend, strategy_name, detail, atr, poc, ob_high, ob_low, fvg = analyze_smc_engine()

        if trend == "NO_DATA":
            bot.reply_to(message, "⚠️ *Price Feed Error.* Try again in a few seconds.", parse_mode="Markdown")
            return

        if trend == "NEUTRAL":
            bot.reply_to(message, f"⚠️ *SMC FILTER: NO TRADE*\n\n*Reason:* `{strategy_name}`\n_{detail}_\n\n*Rule:* Do not enter in consolidation. Wait for smart money to sweep liquidity.", parse_mode="Markdown")
            return

        sl_dist = round(atr * 1.2, 2)
        tp_dist = round(sl_dist * 2.5, 2)  # Higher Risk-to-Reward (1:2.5) for SMC setups

        if trend == "BUY":
            sl_price = round(price - sl_dist, 2)
            tp_price = round(price + tp_dist, 2)
            action_text = "🟢 **SMC BUY ORDER (Liquidity Defended)**"
        else:
            sl_price = round(price + sl_dist, 2)
            tp_price = round(price - tp_dist, 2)
            action_text = "🔴 **SMC SELL ORDER (Liquidity Swept)**"

        risk_amount = balance * 0.02
        lot_size = round(risk_amount / (sl_dist * 100), 2)
        if lot_size < 0.01:
            lot_size = 0.01

        response = (
            f"🏛 *SMC INSTITUTIONAL EXECUTION*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• *Live Spot Price:* `${price:.2f}`\n\n"
            f"🎯 *Smart Money Structures:*\n"
            f"• *Order Block Zone:* `${ob_low:.2f}` – `${ob_high:.2f}`\n"
            f"• *Point of Control (POC):* `${poc:.2f}`\n"
            f"• *Imbalance (FVG):* `{fvg}`\n\n"
            f"📐 *Setup Matrix:*\n"
            f"• *Strategy:* `{strategy_name}`\n"
            f"• *Confirmation:* _{detail}_\n\n"
            f"🚀 *Execution:* {action_text}\n"
            f"• *Bias:* *{trend}*\n"
            f"• *Entry:* `${price:.2f}`\n"
            f"• *Stop Loss:* `${sl_price:.2f}`\n"
            f"• *Take Profit (1:2.5 RR):* `${tp_price:.2f}`\n\n"
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
