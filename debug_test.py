"""
debug_test.py — Minimal bot. Zero DB. Zero decorators.
Tests ONLY whether pyrofork handlers fire on this device.

Run: python debug_test.py
Then send /ping to the bot in private chat.
Expected: "pong" reply + terminal output.
"""
import asyncio
import sys
from pyrogram import Client, filters, idle

# Use same credentials as bot.py
from config import API_ID, API_HASH, BOT_TOKEN

app = Client(
    "debug_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

@app.on_message(filters.command("ping"))
async def ping(client, msg):
    print(f">>> /ping FIRED from user {msg.from_user.id}", flush=True)
    await msg.reply("pong!")

@app.on_message(filters.command("start"))
async def start(client, msg):
    print(f">>> /start FIRED from user {msg.from_user.id}", flush=True)
    await msg.reply("start works!")

@app.on_message()
async def any_msg(client, msg):
    txt = (msg.text or "")[:40]
    print(f">>> ANY MSG: {repr(txt)} from {getattr(msg.from_user,'id','?')}", flush=True)

async def main():
    async with app:
        me = await app.get_me()
        print(f"Bot online: @{me.username} (id={me.id})", flush=True)
        print("Send /ping now...", flush=True)
        await idle()

asyncio.run(main())
