import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import yfinance as yf

# TELEGRAM CONFIGURATION
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# 1. KEEP-ALIVE WEB SERVER (For Render Health Checks)
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

# 2. TELEGRAM HELPER FUNCTIONS
def send_telegram_message(chat_id, message):
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending message: {e}")

def get_gold_price():
    try:
        data = yf.download(tickers="GC=F", period="2d", interval="1h", progress=False)
        if data.empty:
            return None
        if isinstance(data.columns, tuple) or hasattr(data.columns, 'levels'):
            data.columns = data.columns.get_level_values(0)
        return float(data['Close'].iloc[-1])
    except Exception as e:
        print(f"Error fetching price: {e}")
        return None

# 3. COMMAND LISTENER (Responds to you in Telegram)
def poll_telegram_commands():
    last_update_id = 0
    print("Started listening for Telegram commands...")
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id}&timeout=30"
            response = requests.get(url).json()
            
            if "result" in response:
                for update in response["result"]:
                    last_update_id = update["update_id"] + 1
                    
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"].strip().lower()
                        
                        if text == "/start":
                            send_telegram_message(chat_id, "🤖 *Gold Bot is Connected!* Type `/gold` to check the current live price or wait for automatic setups.")
                        elif text == "/gold" or text == "/price":
                            price = get_gold_price()
                            if price:
                                send_telegram_message(chat_id, f"🪙 *Current Gold (XAUUSD) Price:* `{price:.2f}`")
                            else:
                                send_telegram_message(chat_id, "⚠️ Could not fetch live Gold price right now.")
        except Exception as e:
            print(f"Polling error: {e}")
        time.sleep(2)

# Start command listener in the background
threading.Thread(target=poll_telegram_commands, daemon=True).start()

# 4. BACKGROUND ENTRY SCANNER LOOP
def main():
    # Send startup ping to your main chat ID immediately
    if CHAT_ID:
        send_telegram_message(CHAT_ID, "🚀 *Gold Bot restarted and running live!* Send `/gold` in our chat to test it.")
    
    while True:
        # You can add background check logic here later if needed
        time.sleep(900)

if __name__ == "__main__":
    main()
        
