from telethon import TelegramClient, events, functions
import requests, asyncio, threading, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import defaultdict

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
manual_users = set()
user_last_seen = {}
bot_command_context = {}

# === PING SERVER ===
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, format, *args): return

threading.Thread(target=lambda: HTTPServer(('0.0.0.0', 10000), PingHandler).serve_forever(), daemon=True).start()

# === MAIN REPLY FUNCTION ===
async def generate_reply(user_id, message_list):
    system_prompt = {
        "role": "system",
        "content": (
            "You are Mithun. You are talking to your friends and family casually. "
            "You often use Tamil-English mixed messages. Be funny but real, like WhatsApp/Telegram. "
            "Use slang or emojis if needed."
        )
    }
    tokens_used = sum(len(m['content']) for m in message_list)
    if tokens_used > 6000:
        message_list = message_list[-6:]

    messages = [system_prompt] + message_list

    for model in groq_models:
        try:
            print(f"🧠 Trying model: {model}")
            res = requests.post(
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
            if res.status_code == 200:
                ai_reply = res.json()['choices'][0]['message']['content']
                return ai_reply
        except Exception as e:
            print(f"❌ Model {model} failed:", e)
    return "Sorry, couldn't respond now."

# === DETECT MANUAL CHAT USERS ===
async def update_last_seen():
    while True:
        dialogs = await client.get_dialogs()
        for d in dialogs:
            if d.is_user and d.entity.status:
                user_last_seen[d.id] = time.time()
        await asyncio.sleep(10)

# === BOT INSTRUCTION HANDLER ===
@client.on(events.NewMessage(from_users='Telethonpy_bot'))
async def bot_command(event):
    text = event.raw_text.lower()
    if "talk to" in text:
        name = text.split("talk to", 1)[-1].strip()
        async for dialog in client.iter_dialogs():
            if dialog.is_user and name.lower() in dialog.name.lower():
                bot_command_context['target_user'] = dialog.id
                bot_command_context['active'] = True
                bot_command_context['history'] = []
                await event.respond(f"✅ Talking to {dialog.name}")
                return

@client.on(events.NewMessage(incoming=True))
async def main_handler(event):
    sender = await event.get_sender()
    user_id = sender.id
    message = event.raw_text

    # Ignore bots
    if sender.bot:
        return

    # Handle bot-initiated conversation
    if bot_command_context.get('active') and user_id == bot_command_context.get('target_user'):
        print(f"🤖 [BOT CHAT] {sender.first_name}: {message}")
        bot_command_context['history'].append({"role": "user", "content": message})
        reply = await generate_reply(user_id, bot_command_context['history'])
        await event.reply(reply)
        bot_command_context['history'].append({"role": "assistant", "content": reply})
        # Check if user is offline
        if user_id in user_last_seen and time.time() - user_last_seen[user_id] > 30:
            summary = await generate_reply(user_id, bot_command_context['history'] + [{"role": "system", "content": "Summarize this conversation."}])
            await client.send_message('Telethonpy_bot', f"📄 Summary with {sender.first_name}:\n\n{summary}")
            bot_command_context.clear()
        return

    # Skip if user is being manually chatted with
    if user_id in user_last_seen and time.time() - user_last_seen[user_id] < 30:
        print(f"⏸️ Skipping {sender.first_name} (manual chat detected)")
        return

    print(f"📨 {sender.first_name}: {message}")
    conversation_history[user_id].append({"role": "user", "content": message})
    if len(conversation_history[user_id]) > 6:
        conversation_history[user_id] = conversation_history[user_id][-6:]

    reply = await generate_reply(user_id, conversation_history[user_id])
    await event.reply(reply)
    conversation_history[user_id].append({"role": "assistant", "content": reply})

# === RUN EVERYTHING ===
async def main():
    await client.connect()
    print("🤖 Telegram auto-reply bot is starting...")
    asyncio.create_task(update_last_seen())
    await client.run_until_disconnected()

asyncio.run(main())



