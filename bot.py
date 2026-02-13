import os
import json
import time
import requests
import math
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- CONFIG ---
API_ID = int(os.environ.get("API_ID", "your_id"))
API_HASH = os.environ.get("API_HASH", "your_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_token")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "your_folder_id")
# This reads the JSON string from Render Environment Variables
SERVICE_ACCOUNT_INFO = json.loads(os.environ.get("SERVICE_ACCOUNT_JSON"))

# --- AUTHENTICATION (AUTOMATIC - NO LOGIN NEEDED) ---
SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO, scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=creds)

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

def upload_to_drive(file_stream, file_name, total_size, status_msg):
    # 1. Start Resumable Session
    if not creds.valid:
        from google.auth.transport.requests import Request
        creds.refresh(Request())

    metadata = {'name': file_name, 'parents': [DRIVE_FOLDER_ID]}
    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    
    # Initialize
    resp = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
        headers=headers, data=json.dumps(metadata)
    )
    session_url = resp.headers.get("Location")

    # 2. Upload Chunks
    start_time = time.time()
    uploaded = 0
    chunk_size = 5 * 1024 * 1024 # 5MB

    for chunk in file_stream:
        if not chunk: break
        length = len(chunk)
        headers = {
            "Content-Range": f"bytes {uploaded}-{uploaded + length - 1}/{total_size}",
            "Content-Length": str(length)
        }
        requests.put(session_url, headers=headers, data=chunk)
        uploaded += length
        
        # Update Telegram UI
        app.loop.create_task(edit_status(status_msg, uploaded, total_size, start_time))

@app.on_message(filters.document | filters.video)
async def handle_tg_file(client, message: Message):
    media = message.document or message.video
    status_msg = await message.reply_text("🔄 Processing...")
    
    # Generator to stream from Telegram without downloading locally
    async def stream_generator():
        async for chunk in client.stream_media(message):
            yield chunk

    # Run upload in background thread
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, upload_to_drive, stream_generator(), media.file_name, media.file_size, status_msg)
    
    await status_msg.edit(f"✅ **Successfully Uploaded:**\n`{media.file_name}`")

print("Bot is running...")
app.run()