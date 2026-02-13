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
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from google.oauth2 import service_account

# -------------------- WEB SERVER --------------------
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is Active"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host='0.0.0.0', port=port)

# -------------------- CONFIG --------------------
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

upload_semaphore = asyncio.Semaphore(1)
CANCEL_TASKS = {}

# -------------------- HELPERS --------------------
def get_readable_size(size):
    if size == 0:
        return "0B"
    power = 1024
    n = 0
    units = ["B", "KB", "MB", "GB", "TB"]
    while size >= power and n < len(units)-1:
        size /= power
        n += 1
    return f"{round(size,2)} {units[n]}"

async def edit_status(msg, current, total, start_time, task_id):
    percentage = current * 100 / total
    speed = current / (time.time() - start_time) if time.time() - start_time > 0 else 0

    bar_filled = int(percentage // 10)
    bar = "▰" * bar_filled + "▱" * (10 - bar_filled)

    text = (
        f"📤 **Uploading to Drive**\n"
        f"[{bar}] {round(percentage,2)}%\n"
        f"🚀 Speed: {get_readable_size(speed)}/s\n"
        f"📦 {get_readable_size(current)} / {get_readable_size(total)}"
    )

    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]]
    )

    try:
        await msg.edit(text, reply_markup=markup)
    except:
        pass

# -------------------- DRIVE UPLOAD (FIXED) --------------------
async def upload_to_drive_async(file_generator, file_name, total_size, status_msg, task_id):

    if not creds.valid:
        from google.auth.transport.requests import Request
        creds.refresh(Request())

    async with aiohttp.ClientSession() as session:

        # 1️⃣ Create resumable session
        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json"
        }

        metadata = {
            "name": file_name,
            "parents": [DRIVE_FOLDER_ID]
        }

        async with session.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            headers=headers,
            json=metadata
        ) as resp:

            if resp.status not in [200, 201]:
                error = await resp.text()
                print("SESSION ERROR:", error, flush=True)
                return "FAILED"

            upload_url = resp.headers.get("Location")

        print(f"STARTING UPLOAD: {file_name}", flush=True)

        # 2️⃣ Upload full stream in single streaming request
        upload_headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Length": str(total_size),
            "Content-Type": "application/octet-stream",
            "Content-Range": f"bytes 0-{total_size-1}/{total_size}"
        }

        start_time = time.time()
        uploaded = 0

        async def progress_stream():
            nonlocal uploaded
            async for chunk in file_generator:
                if CANCEL_TASKS.get(task_id):
                    return
                uploaded += len(chunk)
                await edit_status(status_msg, uploaded, total_size, start_time, task_id)
                yield chunk

        async with session.put(
            upload_url,
            headers=upload_headers,
            data=progress_stream()
        ) as upload_resp:

            if upload_resp.status in [200, 201]:
                print(f"SUCCESS: {file_name} uploaded.", flush=True)
                return "SUCCESS"
            else:
                error = await upload_resp.text()
                print("UPLOAD FAILED:", error, flush=True)
                return "FAILED"

# -------------------- TELEGRAM HANDLER --------------------
@app.on_message(filters.document | filters.video)
async def handle_file(client, message: Message):

    media = message.document or message.video
    task_id = str(message.id)
    CANCEL_TASKS[task_id] = False

    print(f"RECEIVED: {media.file_name}", flush=True)

    status_msg = await message.reply_text("⏳ Preparing upload...")

    async with upload_semaphore:

        await status_msg.edit("🔄 Starting upload...")

        file_generator = client.stream_media(message)

        try:
            result = await upload_to_drive_async(
                file_generator,
                media.file_name,
                media.file_size,
                status_msg,
                task_id
            )

            if result == "SUCCESS":
                await status_msg.edit("✅ Upload Complete! Check your Drive folder.")
            else:
                await status_msg.edit("❌ Upload failed. Check logs.")

        except Exception as e:
            print("CRITICAL ERROR:", e, flush=True)
            await status_msg.edit(f"❌ Error:\n`{e}`")

# -------------------- CANCEL BUTTON --------------------
@app.on_callback_query()
async def cancel_upload(client, callback_query):
    data = callback_query.data
    if data.startswith("cancel_"):
        task_id = data.split("_")[1]
        CANCEL_TASKS[task_id] = True
        await callback_query.message.edit("❌ Upload Cancelled.")
        await callback_query.answer("Upload cancelled.")

# -------------------- START BOT --------------------
if __name__ == "__main__":
    Thread(target=run_web).start()
    print("BOT STARTED", flush=True)
    app.run()
