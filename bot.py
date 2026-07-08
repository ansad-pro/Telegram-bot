import os
import time
import math
import random
import asyncio
import threading
import urllib.parse
import aiohttp
import aiofiles
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# Koyeb Environment Variables
API_ID = os.environ.get("API_ID")        
API_HASH = os.environ.get("API_HASH")    
BOT_TOKEN = os.environ.get("BOT_TOKEN")  

# Firebase Credentials
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "AIzaSyBo6KSvm_YjKLJxGfJoako9ODOJzignH9c")
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN") 

CURRENT_AUTH_TOKEN = None

app = Client("terabox_bot", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

active_tasks = {}
last_progress_text = {} 

BROWSER_PROFILES = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

def get_random_browser_ua():
    return random.choice(BROWSER_PROFILES)

def run_dummy_server():
    try:
        port = int(os.environ.get("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
        print(f"ℹ️ Fake Port Server started on port {port}")
        server.serve_forever()
    except Exception as e:
        print(f"❌ Dummy server error: {e}")

threading.Thread(target=run_dummy_server, daemon=True).start()

async def get_valid_token(force_refresh=False):
    global CURRENT_AUTH_TOKEN
    if not REFRESH_TOKEN:
        return None
    if not CURRENT_AUTH_TOKEN or force_refresh:
        refresh_url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
        payload = {"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN}
        async with aiohttp.ClientSession() as session:
            async with session.post(refresh_url, data=payload) as response:
                if response.status == 200:
                    res_data = await response.json()
                    CURRENT_AUTH_TOKEN = res_data.get("id_token")
                else:
                    CURRENT_AUTH_TOKEN = None
    return CURRENT_AUTH_TOKEN

def format_size(bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024

async def progress_bar(current, total, status_msg, start_time, action, user_id):
    if not total:
        return
    now = time.time()
    diff = now - start_time
    if round(diff % 3) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        eta = round((total - current) / speed) if speed > 0 else 0
        bar_length = 10
        filled_length = int(math.floor(percentage / bar_length))
        bar = '■' * filled_length + '□' * (bar_length - filled_length)
        progress_str = (
            f"⚡️ **{action}...**\n\n"
            f"├ [{bar}] {percentage:.1f}%\n"
            f"├ **Size:** {format_size(current)} / {format_size(total)}\n"
            f"├ **Speed:** {format_size(speed)}/s\n"
            f"└ **ETA:** {eta}s"
        )
        if last_progress_text.get(user_id) == progress_str:
            return
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Process", callback_data=f"cancel_{user_id}")]])
        try:
            await status_msg.edit_text(progress_str, reply_markup=reply_markup)
            last_progress_text[user_id] = progress_str 
        except Exception:
            pass

# --- NEW: MULTI-CONNECTION PARALLEL DOWNLOADER LOGIC ---
async def download_chunk(session, url, start, end, filename, chunk_id, headers, progress_tracker):
    chunk_headers = headers.copy()
    chunk_headers['Range'] = f'bytes={start}-{end}'
    
    async with session.get(url, headers=chunk_headers) as resp:
        if resp.status not in (200, 206):
            raise Exception(f"Chunk {chunk_id} failed: {resp.status}")
        
        async with aiofiles.open(filename, 'rb+') as f:
            await f.seek(start)
            async for data in resp.content.iter_chunked(1024 * 256):
                await f.write(data)
                progress_tracker['downloaded'] += len(data)

async def parallel_download(url, filename, headers, status_msg, user_id, num_connections=8):
    timeout = aiohttp.ClientTimeout(total=None, sock_read=60, sock_connect=30)
    connector = aiohttp.TCPConnector(limit=num_connections + 4, ssl=False, force_close=False)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async with session.head(url, headers=headers, allow_redirects=True) as head_resp:
            total_size = int(head_resp.headers.get('content-length', 0))
            accept_ranges = head_resp.headers.get('accept-ranges', '').lower()
        
        if total_size == 0:
            raise Exception("Could not determine file size")
        
        if accept_ranges != 'bytes':
            print("⚠️ Server doesn't support Range. Falling back to single connection.")
            num_connections = 1
        
        # Pre-allocate file space safely
        async with aiofiles.open(filename, 'wb') as f:
            await f.truncate(total_size)
        
        chunk_size = total_size // num_connections
        ranges = []
        for i in range(num_connections):
            start = i * chunk_size
            end = start + chunk_size - 1 if i < num_connections - 1 else total_size - 1
            ranges.append((start, end))
        
        progress_tracker = {'downloaded': 0}
        start_time = time.time()
        
        async def update_progress():
            while progress_tracker['downloaded'] < total_size:
                await progress_bar(progress_tracker['downloaded'], total_size, status_msg, start_time, "Downloading", user_id)
                await asyncio.sleep(2)
        
        progress_task = asyncio.create_task(update_progress())
        
        try:
            tasks = [
                download_chunk(session, url, start, end, filename, i, headers, progress_tracker)
                for i, (start, end) in enumerate(ranges)
            ]
            await asyncio.gather(*tasks)
        finally:
            progress_task.cancel()
        
        await progress_bar(total_size, total_size, status_msg, start_time, "Downloading", user_id)
        return total_size
# -----------------------------------------------------

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("Hello! Terabox link ayachu tharu. Parallel multi-connection download വഴി ഫയലുകൾ സൂപ്പർ ഫാസ്റ്റായി അയച്ചു തരാം! 🚀🍿")

DOMAINS_REGEX = r"(terabox\.app|teraboxshare\.com|terabox\.com|1024terabox\.com|teraboxlink\.com|terasharefile\.com|terafileshare\.com|terasharelink\.com)"

@app.on_message(filters.text & filters.regex(DOMAINS_REGEX))
async def handle_terabox_link(client, message: Message):
    user_id = message.from_user.id
    if user_id in active_tasks:
        await message.reply_text("❌ നിന്റെ ഒരു ടാസ്ക് ഓൾറെഡി നടക്കുന്നുണ്ട്!")
        return

    status_msg = await message.reply_text("🔍 Terabox link check cheyyunnu...")
    filename = None
    delete_status = True  
    active_tasks[user_id] = asyncio.current_task()

    try:
        url = message.text
        encoded_url = urllib.parse.quote(url)
        api_url = f"https://api.tera-peek.in/api/resolve?url={encoded_url}&mode=download"
        
        token = await get_valid_token()
        if not token:
            await status_msg.edit_text("❌ Token error!")
            delete_status = False
            return

        api_success = False
        data = None
        for attempt in range(2): 
            headers = {"Authorization": f"Bearer {token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        api_success = True
                        break
                    elif response.status in [401, 403] and attempt == 0:
                        token = await get_valid_token(force_refresh=True)
                    else:
                        await status_msg.edit_text(f"❌ API error! Status: {response.status}")
                        delete_status = False
                        return

        if not api_success or not data:
            await status_msg.edit_text("❌ Response labhichilla.")
            delete_status = False
            return

        files = data.get("files", [])
        if not files:
            await status_msg.edit_text("❌ Files onnum kandilla.")
            delete_status = False
            return
        
        file_data = files[0]
        dlink = file_data.get("dlink")
        filename = file_data.get("filename", "video.mp4")

        if not dlink:
            await status_msg.edit_text("❌ Dlink generate cheyyan pattiyilla.")
            delete_status = False
            return

        # --- INTEGRATED PARALLEL DOWNLOAD PROCESS ---
        await status_msg.edit_text("⬇️ Multi-connection download start cheyyunnu... (8 threads)")
        
        random_ua = get_random_browser_ua()
        download_headers = {
            "User-Agent": random_ua,
            "Referer": "https://www.terabox.com/",
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        api_provided_headers = file_data.get("headers")
        if api_provided_headers and isinstance(api_provided_headers, dict):
            for k, v in api_provided_headers.items():
                if k.lower() not in ["user-agent", "referer"]:
                    download_headers[k] = str(v)
        
        try:
            # Koyeb Free Tier RAM ലിമിറ്റ് ഉള്ളതുകൊണ്ട് സുരക്ഷിതമായി 8 connections സെറ്റ് ചെയ്തു
            await parallel_download(dlink, filename, download_headers, status_msg, user_id, num_connections=8)
        except Exception as e:
            await status_msg.edit_text(f"❌ **Download Failed!**\n`{str(e)}`")
            delete_status = False
            return
        # --------------------------------------------

        if os.path.exists(filename) and os.path.getsize(filename) < 50 * 1024:
            delete_status = False
            if os.path.exists(filename): os.remove(filename)
            await status_msg.edit_text("❌ Corrupted file received from Terabox.")
            return

        await status_msg.edit_text("⬆️ Telegram-lekku upload cheyyunnu...")
        upload_start_time = time.time()
        await message.reply_video(
            video=filename,
            caption=f"**Title:** `{filename}`\n\nDownloaded via Bot 🚀",
            supports_streaming=True,
            progress=progress_bar, 
            progress_args=(status_msg, upload_start_time, "Uploading", user_id)
        )

    except asyncio.CancelledError:
        await message.reply_text("🛑 **Process Cancelled!**")
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")
    finally:
        active_tasks.pop(user_id, None)
        last_progress_text.pop(user_id, None)
        if filename and os.path.exists(filename):
            os.remove(filename)
        if delete_status:
            try: await status_msg.delete()
            except Exception: pass

@app.on_callback_query(filters.regex(r"^cancel_(\d+)"))
async def cancel_callback(client, callback_query: CallbackQuery):
    target_user_id = int(callback_query.data.split("_")[1])
    if callback_query.from_user.id != target_user_id:
        await callback_query.answer("❌ Ith ninte task alla!", show_alert=True)
        return
    task = active_tasks.get(target_user_id)
    if task:
        task.cancel()
        await callback_query.answer("🛑 Cancelling...")
    else:
        await callback_query.answer("⚠️ Active task illa.", show_alert=True)

if __name__ == "__main__":
    app.run()
