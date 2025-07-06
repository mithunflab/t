import os
import asyncio
from telethon import TelegramClient, events
import requests
from collections import defaultdict

# === CONFIG ===
api_id = 22986717
api_hash = '1d1206253d640d42f488341e3b4f0a2f'
groq_api_key = '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'

# Fallback models
groq_models = [
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma-7b-it",
    "llama2-70b-4096"
]

# Port for Render Web Service (mock server to keep service alive)
from http.server import BaseHTTPRequestHandler, HTTPServer
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Telegram bot is running!')

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("", port), SimpleHandler)
    print(f"🌐 HTTP server running on port {port}...")
    server.serve_forever()

client = TelegramClient('session_mithun', api_id, api_hash)
conversation_history = defaultdict(list)

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    sender = await event.get_sender()
    message = event.raw_text
    if event.is_private and not sender.bot:
        user_id = sender.id
        conversation_history[user_id].append({"role": "user", "content": message})
        if len(conversation_history[user_id]) > 6:
            conversation_history[user_id] = conversation_history[user_id][-6:]

        messages = [
            {"role": "system", "content": "You are Mithun. Talk casually with Tamil-English mix. Be friendly, humorous, and real."}
        ] + conversation_history[user_id]

        ai_reply = None
        for model in groq_models:
            try:
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
                        await event.reply(ai_reply)
                        conversation_history[user_id].append({"role": "assistant", "content": ai_reply})
                        break
            except Exception as e:
                print(f"❌ Error with model {model}: {str(e)}")
        if not ai_reply:
            print("❌ All models failed.")

async def main():
    await client.start()
    await client.run_until_disconnected()

loop = asyncio.get_event_loop()
loop.create_task(main())
run_server()
