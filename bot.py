import asyncio
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import os, json, time, math, aiohttp, sys
from flask import Flask
from threading import Thread
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from google.oauth2 import service_account

# --- WEB SERVER ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Bot is Active"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

# --- CONFIG ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
SERVICE_ACCOUNT_INFO = json.loads(os.environ.get("SERVICE_ACCOUNT_JSON"))

upload_semaphore = asyncio.Semaphore(1) 
CANCEL_TASKS = {}
# Set to 50MB for better visibility in logs
LOG_THRESHOLD = 50 * 1024 * 1024 

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def get_readable_size(size_in_bytes):
    if size_in_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_in_bytes, 1024)))
    return f"{round(size_in_bytes / math.pow(1024, i), 2)} {size_name[i]}"

async def edit_status(status_msg, current, total, start_time, task_id):
    percentage = current * 100 / total
    speed = current / (time.time() - start_time) if (time.time() - start_time) > 0 else 0
    bar = "".join(["▰" for i in range(math.floor(percentage / 10))]).ljust(10, "▱")
    
    text = (f"📤 **Low-RAM Upload**\n"
            f"[{bar}] {round(percentage, 2)}%\n"
            f"🚀 Speed: {get_readable_size(speed)}/s\n"
            f"📦 Uploaded: {get_readable_size(current)} / {get_readable_size(total)}")
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]])
    try: await status_msg.edit(text, reply_markup=markup)
    except: pass

async def upload_to_drive_async(file_generator, file_name, total_size, status_msg, task_id):
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

        # FORCE PRINT IMMEDIATELY
        print(f"DEBUG: Starting real-time stream for {file_name} ({get_readable_size(total_size)})", flush=True)
        
        start_time = time.time()
        uploaded = 0
        last_log_size = 0
        
        async for chunk in file_generator:
            if CANCEL_TASKS.get(task_id): return "CANCELLED"
            if not chunk: break
            
            chunk_headers = {
                "Content-Range": f"bytes {uploaded}-{uploaded + len(chunk) - 1}/{total_size}",
                "Content-Length": str(len(chunk))
            }
            
            async with session.put(session_url, headers=chunk_headers, data=chunk) as r:
                uploaded += len(chunk)
                
                # Update every 50MB in logs
                if (uploaded - last_log_size) >= LOG_THRESHOLD or uploaded == total_size:
                    print(f"PROGRESS: {file_name} -> {get_readable_size(uploaded)} completed", flush=True)
                    await edit_status(status_msg, uploaded, total_size, start_time, task_id)
                    last_log_size = uploaded

        return "SUCCESS"

@app.on_message(filters.document | filters.video)
async def handle_tg_file(client, message: Message):
    media = message.document or message.video
    task_id = str(message.id)
    CANCEL_TASKS[task_id] = False
    
    print(f"RECEIVED: New file request - {media.file_name}", flush=True)
    status_msg = await message.reply_text("⏳ Queued... checking Render RAM.")
    
    async with upload_semaphore:
        await status_msg.edit(f"🔄 **Uploading...**\nLogs updating every 50MB.")
        file_generator = client.stream_media(message)
        try:
            result = await upload_to_drive_async(file_generator, media.file_name, media.file_size, status_msg, task_id)
            if result == "CANCELLED":
                await status_msg.edit("❌ Upload Cancelled.")
            else:
                await status_msg.edit(f"✅ **Done!** Check Drive folder.")
        except Exception as e:
            print(f"CRITICAL ERROR: {e}", flush=True)
            await status_msg.edit(f"❌ Error: `{e}`")

if __name__ == "__main__":
    Thread(target=run_web).start()
    print("BOT STARTED: Unbuffered logging enabled.", flush=True)
    app.run()
