import asyncio
# --- FIX FOR EVENT LOOP ERROR ---
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

# Cancellation Tracker
CANCEL_TASKS = {}

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def get_readable_size(size_in_bytes):
    if size_in_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_in_bytes, 1024)))
    return f"{round(size_in_bytes / math.pow(1024, i), 2)} {size_name[i]}"

async def edit_status(status_msg, current, total, start_time, task_id, force=False):
    now = time.time()
    last_update = getattr(status_msg, "last_update", 0)
    if not force and (now - last_update) < 10: 
        return
    
    status_msg.last_update = now
    percentage = current * 100 / total
    speed = current / (now - start_time) if (now - start_time) > 0 else 0
    bar = "".join(["▰" for i in range(math.floor(percentage / 10))]).ljust(10, "▱")
    
    text = (f"📤 **Uploading...**\n"
            f"[{bar}] {round(percentage, 2)}%\n"
            f"🚀 Speed: {get_readable_size(speed)}/s\n"
            f"📦 Done: {get_readable_size(current)} of {get_readable_size(total)}")
    
    # Inline button for Cancellation
    reply_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel Upload", callback_data=f"cancel_{task_id}")
    ]])

    try:
        await status_msg.edit(text, reply_markup=reply_markup)
    except: pass

async def upload_to_drive_async(file_generator, file_name, total_size, status_msg, task_id):
    if not creds.valid:
        from google.auth.transport.requests import Request
        creds.refresh(Request())

    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    metadata = {'name': file_name, 'parents': [DRIVE_FOLDER_ID]}
    
    async with aiohttp.ClientSession() as session:
        # 1. Start Resumable Session
        async with session.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            headers=headers, json=metadata
        ) as resp:
            session_url = resp.headers.get("Location")

        start_time = time.time()
        uploaded = 0
        
        # 2. Upload Chunks
        async for chunk in file_generator:
            # Check if user clicked cancel
            if CANCEL_TASKS.get(task_id):
                print(f"Task {task_id} was cancelled by user.")
                # Delete file from Drive session (optional but clean)
                await session.delete(session_url)
                return "CANCELLED"

            if not chunk: break
            length = len(chunk)
            chunk_headers = {
                "Content-Range": f"bytes {uploaded}-{uploaded + length - 1}/{total_size}",
                "Content-Length": str(length)
            }
            async with session.put(session_url, headers=chunk_headers, data=chunk) as r:
                uploaded += length
                await edit_status(status_msg, uploaded, total_size, start_time, task_id)

        return "SUCCESS"

@app.on_message(filters.document | filters.video)
async def handle_tg_file(client, message: Message):
    media = message.document or message.video
    task_id = str(message.id) # Unique ID for this specific message/upload
    CANCEL_TASKS[task_id] = False

    status_msg = await message.reply_text("🔄 Initiating Stream...", 
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]]))
    status_msg.last_update = time.time()
    
    file_generator = client.stream_media(message)
    try:
        result = await upload_to_drive_async(file_generator, media.file_name, media.file_size, status_msg, task_id)
        
        if result == "CANCELLED":
            await status_msg.edit(f"❌ **Upload Cancelled:**\n`{media.file_name}`")
        else:
            await status_msg.edit(f"✅ **Success!**\nFile: `{media.file_name}`")
            
    except Exception as e:
        print(f"Error: {e}")
        await status_msg.edit(f"❌ **Error:** `{str(e)}` \n(Check if Drive folder is shared with Service Account)")
    finally:
        # Cleanup
        if task_id in CANCEL_TASKS:
            del CANCEL_TASKS[task_id]

# --- CALLBACK HANDLER FOR CANCEL BUTTON ---
@app.on_callback_query(filters.regex(r"^cancel_"))
async def cancel_callback(client, query: CallbackQuery):
    task_id = query.data.split("_")[1]
    if task_id in CANCEL_TASKS:
        CANCEL_TASKS[task_id] = True
        await query.answer("Cancelling upload... Please wait.", show_alert=True)
    else:
        await query.answer("Task not found or already finished.", show_alert=False)

if __name__ == "__main__":
    Thread(target=run_web).start()
    print("Bot starting with Cancel Button support...")
    app.run()
