import asyncio

# --- FIX FOR THE 'NO CURRENT EVENT LOOP' ERROR ---
# This must be at the very top before any other imports
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import os
import json
import time
import math
import aiohttp
from flask import Flask
from threading import Thread
from pyrogram import Client, filters
from pyrogram.types import Message
from google.oauth2 import service_account

# --- DUMMY WEB SERVER FOR RENDER ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is alive and running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

# --- BOT CONFIG ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
SERVICE_ACCOUNT_INFO = json.loads(os.environ.get("SERVICE_ACCOUNT_JSON"))

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO, scopes=SCOPES
)

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def get_readable_size(size_in_bytes):
    if size_in_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_in_bytes, 1024)))
    return f"{round(size_in_bytes / math.pow(1024, i), 2)} {size_name[i]}"

async def edit_status(status_msg, current, total, start_time):
    now = time.time()
    diff = now - start_time
    if diff < 2: return 
    percentage = current * 100 / total
    speed = current / diff
    bar = "".join(["▰" for i in range(math.floor(percentage / 10))]).ljust(10, "▱")
    
    text = (f"📤 **Uploading to Drive...**\n"
            f"[{bar}] {round(percentage, 2)}%\n"
            f"🚀 Speed: {get_readable_size(speed)}/s\n"
            f"📦 Size: {get_readable_size(current)} / {get_readable_size(total)}")
    try:
        await status_msg.edit(text)
    except: pass

async def upload_to_drive_async(file_generator, file_name, total_size, status_msg):
    if not creds.valid:
        from google.auth.transport.requests import Request
        creds.refresh(Request())

    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    metadata = {'name': file_name, 'parents': [DRIVE_FOLDER_ID]}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            headers=headers, json=metadata
        ) as resp:
            session_url = resp.headers.get("Location")

        start_time = time.time()
        uploaded = 0
        async for chunk in file_generator:
            if not chunk: break
            length = len(chunk)
            chunk_headers = {
                "Content-Range": f"bytes {uploaded}-{uploaded + length - 1}/{total_size}",
                "Content-Length": str(length)
            }
            async with session.put(session_url, headers=chunk_headers, data=chunk) as r:
                uploaded += length
                await edit_status(status_msg, uploaded, total_size, start_time)

@app.on_message(filters.document | filters.video)
async def handle_tg_file(client, message: Message):
    media = message.document or message.video
    status_msg = await message.reply_text("🔄 Connecting to Google Drive...")
    file_generator = client.stream_media(message)
    try:
        await upload_to_drive_async(file_generator, media.file_name, media.file_size, status_msg)
        await status_msg.edit(f"✅ **Success!**\nFile: `{media.file_name}`")
    except Exception as e:
        await status_msg.edit(f"❌ **Error:** `{str(e)}`")

if __name__ == "__main__":
    # Start Web Server for Render
    Thread(target=run_web).start()
    print("Web server live. Starting Bot loop...")
    
    # Standard Pyrogram run
    app.run()
