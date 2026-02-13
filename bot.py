import asyncio
# --- FIX FOR PYTHON 3.12+ EVENT LOOP ERROR ---
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import os
import json
import time
import math
import aiohttp # We use aiohttp instead of requests for better performance
from pyrogram import Client, filters
from pyrogram.types import Message
from google.oauth2 import service_account

# --- CONFIG ---
API_ID = int(os.environ.get("API_ID", "your_id"))
API_HASH = os.environ.get("API_HASH", "your_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_token")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "your_folder_id")
SERVICE_ACCOUNT_INFO = json.loads(os.environ.get("SERVICE_ACCOUNT_JSON"))

# --- GOOGLE AUTH ---
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
    if diff < 1: return
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
    # Refresh token
    if not creds.valid:
        from google.auth.transport.requests import Request
        creds.refresh(Request())

    # 1. Start Resumable Session
    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    metadata = {'name': file_name, 'parents': [DRIVE_FOLDER_ID]}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            headers=headers, json=metadata
        ) as resp:
            session_url = resp.headers.get("Location")

        # 2. Stream Chunks
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
    status_msg = await message.reply_text("🔄 Starting Stream...")
    
    # Use Pyrogram's stream_media
    file_generator = client.stream_media(message)
    
    try:
        await upload_to_drive_async(file_generator, media.file_name, media.file_size, status_msg)
        await status_msg.edit(f"✅ **Successfully Uploaded:**\n`{media.file_name}`")
    except Exception as e:
        await status_msg.edit(f"❌ **Error:** `{str(e)}` \nMake sure you shared the Drive folder with the service account email!")

print("Bot is starting...")
app.run()
