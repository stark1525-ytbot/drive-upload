import asyncio
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import os, json, time, math, aiohttp
from flask import Flask
from threading import Thread
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from google.oauth2 import service_account

# --- WEB SERVER FOR RENDER ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Bot is optimized for Low RAM (100MB Update Interval)."

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

# --- CONFIG ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
SERVICE_ACCOUNT_INFO = json.loads(os.environ.get("SERVICE_ACCOUNT_JSON"))

# GLOBAL LIMITS
upload_semaphore = asyncio.Semaphore(1) 
CANCEL_TASKS = {}
UPDATE_THRESHOLD = 100 * 1024 * 1024  # 100 MB

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
    
    text = (f"📤 **Low-RAM Upload Mode**\n"
            f"[{bar}] {round(percentage, 2)}%\n"
            f"🚀 Speed: {get_readable_size(speed)}/s\n"
            f"📦 Uploaded: {get_readable_size(current)} / {get_readable_size(total)}\n\n"
            f"⏳ *Next status update at +100MB...*")
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]])
    try:
        await status_msg.edit(text, reply_markup=markup)
    except: pass

async def upload_to_drive_async(file_generator, file_name, total_size, status_msg, task_id):
    if not creds.valid:
        from google.auth.transport.requests import Request
        creds.refresh(Request())

    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    metadata = {'name': file_name, 'parents': [DRIVE_FOLDER_ID]}
    
    async with aiohttp.ClientSession() as session:
        # Start Session
        async with session.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            headers=headers, json=metadata
        ) as resp:
            session_url = resp.headers.get("Location")

        print(f"INITIATED: {file_name}")
        start_time = time.time()
        uploaded = 0
        last_update_size = 0
        
        async for chunk in file_generator:
            if CANCEL_TASKS.get(task_id): return "CANCELLED"
            if not chunk: break
            
            length = len(chunk)
            chunk_headers = {
                "Content-Range": f"bytes {uploaded}-{uploaded + length - 1}/{total_size}",
                "Content-Length": str(length)
            }
            
            async with session.put(session_url, headers=chunk_headers, data=chunk) as r:
                uploaded += length
                
                # Check if we passed the 100MB mark or if file is finished
                if (uploaded - last_update_size) >= UPDATE_THRESHOLD or uploaded == total_size:
                    print(f"LOG: {file_name} Progress -> {get_readable_size(uploaded)}")
                    await edit_status(status_msg, uploaded, total_size, start_time, task_id)
                    last_update_size = uploaded

        return "SUCCESS"

@app.on_message(filters.document | filters.video)
async def handle_tg_file(client, message: Message):
    media = message.document or message.video
    task_id = str(message.id)
    CANCEL_TASKS[task_id] = False

    status_msg = await message.reply_text("⏳ Queued... waiting for RAM to clear.")
    
    async with upload_semaphore:
        await status_msg.edit(f"🔄 **Uploading {media.file_name}**\nStatus will update every 100MB.")
        
        # We read the file in small chunks to keep RAM usage low
        file_generator = client.stream_media(message)
        
        try:
            result = await upload_to_drive_async(file_generator, media.file_name, media.file_size, status_msg, task_id)
            
            if result == "CANCELLED":
                await status_msg.edit(f"❌ Cancelled: `{media.file_name}`")
            else:
                await status_msg.edit(f"✅ **Finished!**\n`{media.file_name}`\nTotal: {get_readable_size(media.file_size)}")
        except Exception as e:
            await status_msg.edit(f"❌ Error: `{str(e)}`")
        finally:
            if task_id in CANCEL_TASKS: del CANCEL_TASKS[task_id]

@app.on_callback_query(filters.regex(r"^cancel_"))
async def cancel_callback(client, query: CallbackQuery):
    task_id = query.data.split("_")[1]
    if task_id in CANCEL_TASKS:
        CANCEL_TASKS[task_id] = True
        await query.answer("Cancelling upload...")
    else:
        await query.answer("Already completed.")

if __name__ == "__main__":
    Thread(target=run_web).start()
    print("Bot started. Optimization: 100MB update interval.")
    app.run()
