from telethon import TelegramClient, events
import requests
from collections import defaultdict
import asyncio
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# === CONFIG ===
api_id = 22986717
api_hash = '1d1206253d640d42f488341e3b4f0a2f'
groq_api_key = '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'

groq_models = [
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma-7b-it",
    "llama2-70b-4096"
]

client = TelegramClient('session_mithun', api_id, api_hash)
conversation_history = defaultdict(list)
manual_reply_tracker = defaultdict(lambda: 0)
MANUAL_REPLY_TIMEOUT = 48 # in seconds

# === Uptime Server ===
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, format, *args):
        return

def start_web():
    server = HTTPServer(('0.0.0.0', 10000), PingHandler)
    print("✅ Web ping server started on port 10000")
    server.serve_forever()

threading.Thread(target=start_web, daemon=True).start()

# === Track Your Manual Messages ===
@client.on(events.NewMessage(outgoing=True))
async def track_manual_reply(event):
    if event.is_private:
        user_id = event.chat_id
        manual_reply_tracker[user_id] = time.time()
        print(f"⏱️ You manually replied to user {user_id}. AI replies paused temporarily.")

# === AI Auto-Reply ===
@client.on(events.NewMessage(incoming=True))
async def ai_reply_handler(event):
    sender = await event.get_sender()
    message = event.raw_text

    if event.is_private and not sender.bot:
        user_id = sender.id

        # Check if you manually messaged them recently
        if time.time() - manual_reply_tracker[user_id] < MANUAL_REPLY_TIMEOUT:
            print(f"⛔ Skipping reply to {sender.first_name} (manual reply detected recently)")
            return

        print(f"\n📩 {sender.first_name}: {message}")
        conversation_history[user_id].append({"role": "user", "content": message})

        # Keep history short
        if len(conversation_history[user_id]) > 6:
            conversation_history[user_id] = conversation_history[user_id][-6:]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Mithun. You are talking to your friends and family casually. "
                    "You often use Tamil-English mixed messages. You like to be funny but real. "
                    "Speak in a way that feels like a chill WhatsApp or Telegram chat. Use slang and emojis if needed."
                )
            }
        ] + conversation_history[user_id]

        for model in groq_models:
            try:
                print(f"🧠 Trying model: {model}")
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0.7
                    }
                )

                if response.status_code == 200:
                    json_data = response.json()
                    if "choices" in json_data:
                        ai_reply = json_data['choices'][0]['message']['content']
                        print(f"🤖 Replying with {model}: {ai_reply}")
                        await event.reply(ai_reply)
                        conversation_history[user_id].append({"role": "assistant", "content": ai_reply})
                        break
            except Exception as e:
                print(f"❌ Model {model} error:", str(e))

# === Main ===
async def main():
    await client.connect()
    print("🤖 Telegram auto-reply bot is starting...")
    await client.run_until_disconnected()

asyncio.run(main())


