from telethon import TelegramClient, events
import requests
import asyncio
import threading
from flask import Flask
from collections import defaultdict
import re
import time

# === CONFIG ===
api_id = 22986717
api_hash = '2d1206253d640d42f488341e3b4f0a2f'
# Primary AI key for general chats
main_groq_api_key = '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'
# Special key/model for command-based chats
telethonbot_groq_key = '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'
session_name = 'session_mithun'
bot_username = 'Telethonpy_bot'
ignored_usernames = {'Telethonpy_bot', 'Lunaclaude_bot'}

# === STATE ===
client = TelegramClient(session_name, api_id, api_hash)
conversation_history = defaultdict(list)
pause_ai = set()
force_ai = set()
manual_chatting_with = None
active_conversations = {}  # user_id -> last_seen_time

# === UPTIME SERVER ===
app = Flask(__name__)
@app.route('/', methods=['GET', 'HEAD'])
def ping():
    return 'Bot is alive!', 200
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()

# === AI UTILITIES ===
def generate_ai_reply(messages, api_key, model=None, default_models=None):
    # If specific model provided, use only that
    models = [model] if model else default_models
    for m in models:
        try:
            res = requests.post(
                'https://api.groq.com/openai/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                },
                json={
                    'model': m,
                    'messages': messages[-10:],
                    'temperature': 0.7
                }
            )
            j = res.json()
            if res.status_code == 200 and 'choices' in j:
                return j['choices'][0]['message']['content']
        except Exception as e:
            print(f'Error in model {m}: {e}')
    return '🤖 Sorry, something went wrong.'

# Default fallback models
default_models = [
    'llama3-70b-8192', 'llama3-8b-8192', 'gemma-7b-it', 'llama2-70b-4096'
]

# === EVENT HANDLER ===
@client.on(events.NewMessage(incoming=True))
async def handle_event(event):
    global manual_chatting_with
    sender = await event.get_sender()
    uid = sender.id
    uname = (sender.username or '').lower()
    text = event.raw_text.strip()

    # Ignore messages from ignored bots
    if uname in {u.lower() for u in ignored_usernames}:
        return

    # COMMAND PARSING: messages to your bot
    if uname == bot_username.lower():
        # match commands
        cmd_match = re.search(r'(?i)\b(msg|message|start chat|talk to|tell)\b', text)
        if cmd_match:
            parts = re.findall(r'@\w+|\+?\d{10,15}|him|her', text)
            body = re.sub(r'(?i)(msg|message|start chat|talk to|tell)\s+(@\w+|\+?\d{10,15}|him|her)', '', text).strip()
            if parts:
                target = parts[0]
                try:
                    # resolve entity
                    if target.lower() in ['him', 'her'] and manual_chatting_with:
                        entity_id = manual_chatting_with
                    else:
                        entity = await client.get_input_entity(target)
                        entity_id = entity.user_id

                    # generate reply via special model
                    reply = generate_ai_reply(
                        messages=[{'role':'user','content': body or ' ' }],
                        api_key=telethonbot_groq_key,
                        model='meta-llama/llama-4-scout-17b-16e-instruct'
                    )
                    # send to user
                    await client.send_message(entity_id, reply)
                    active_conversations[entity_id] = time.time()
                    await event.reply(f'✅ Started chat with {target}.')
                except Exception as e:
                    await event.reply(f'❌ Could not start chat: {e}')
        return

    # PAUSE / FORCE
    if text == '/':
        pause_ai.add(uid)
        await event.reply('⏸️ AI paused for this user.')
        return
    if text == '\\':
        force_ai.add(uid)
        await event.reply('✅ AI forced on for this user.')
        return
    if uid in pause_ai and uid not in force_ai:
        return

    # MANUAL CHAT DETECTION
    me = await client.get_me()
    if event.is_private:
        async for m in client.iter_messages(event.chat_id, limit=1, from_user=me):
            if m.date.timestamp() > event.message.date.timestamp():
                manual_chatting_with = uid
                return
    if manual_chatting_with == uid and uid not in force_ai:
        return

    # AUTO-REPLY
    conversation_history[uid].append({'role':'user','content': text})
    conversation_history[uid] = conversation_history[uid][-6:]
    prompt = [{'role':'system','content':'You are Mithun, chatting casually in Tamil-English mix.'}] + conversation_history[uid]
    reply = generate_ai_reply(prompt, api_key=main_groq_api_key, default_models=default_models)
    await event.reply(reply)
    conversation_history[uid].append({'role':'assistant','content': reply})
    active_conversations[uid] = time.time()

# === SUMMARY MONITOR ===
async def monitor_summary():
    while True:
        now = time.time()
        to_del = []
        for uid, last in active_conversations.items():
            if now - last > 120:
                hist = conversation_history.get(uid, [])[-6:]
                if hist:
                    summary_prompt = [{'role':'system','content':
                        'Summarize this conversation in 2 lines including what Mithun said and user replies.'
                    }] + hist
                    summary = generate_ai_reply(summary_prompt, api_key=main_groq_api_key, default_models=default_models)
                    await client.send_message(bot_username, f'📄 Summary for chat with {uid}:\n{summary}')
                to_del.append(uid)
        for uid in to_del:
            active_conversations.pop(uid, None)
        await asyncio.sleep(30)

# === MAIN ===
async def main():
    await client.start()
    print('🤖 Bot is running!')
    await asyncio.gather(
        client.run_until_disconnected(),
        monitor_summary()
    )

asyncio.run(main())


