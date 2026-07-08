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

# Parallel download config
NUM_CONNECTIONS = int(os.environ.get("NUM_CONNECTIONS", 16))

app = Client("terabox_bot", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

active_tasks = {}
last_progress_text = {}

# --- USER-AGENT ROTATION POOL ---
BROWSER_PROFILES = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

def get_random_browser_ua():
    return random.choice(BROWSER_PROFILES)

# --- FAKE PORT SERVER FOR KOYEB ---
def run_dummy_server():
    try:
        port = int(os.environ.get("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
        print(f"ℹ️ Fake Port Server started on port {port}")
        server.serve_forever()
    except Exception as e:
        print(f"❌ Dummy server error: {e}")

threading.Thread(target=run_dummy_server, daemon=True).start()

# --- FIREBASE TOKEN REFRESH ---
async def get_valid_token(force_refresh=False):
    global CURRENT_AUTH_TOKEN

    if not REFRESH_TOKEN:
        print("❌ ERROR: REFRESH_TOKEN is not set!")
        return None

    if not CURRENT_AUTH_TOKEN or force_refresh:
        print("🔄 Fetching fresh ID Token from Firebase...")
        refresh_url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(refresh_url, data=payload) as response:
                if response.status == 200:
                    res_data = await response.json()
                    CURRENT_AUTH_TOKEN = res_data.get("id_token")
                    print("✅ New ID Token successfully generated!")
                else:
                    print(f"❌ Firebase token refresh failed! Status: {response.status}")
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

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel Process", callback_data=f"cancel_{user_id}")]
        ])
        try:
            await status_msg.edit_text(progress_str, reply_markup=reply_markup)
            last_progress_text[user_id] = progress_str
        except Exception:
            pass

# --- MULTI-CONNECTION PARALLEL DOWNLOADER ---
async def download_chunk(session, url, start, end, filename, chunk_id, headers, progress_tracker, max_retries=3):
    for attempt in range(max_retries):
        try:
            chunk_headers = headers.copy()
            chunk_headers['Range'] = f'bytes={start}-{end}'

            async with session.get(url, headers=chunk_headers) as resp:
                if resp.status not in (200, 206):
                    raise Exception(f"Chunk {chunk_id} HTTP {resp.status}")

                async with aiofiles.open(filename, 'rb+') as f:
                    await f.seek(start)
                    async for data in resp.content.iter_chunked(1024 * 256):
                        await f.write(data)
                        progress_tracker['downloaded'] += len(data)
            return
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            print(f"⚠️ Chunk {chunk_id} retry {attempt+1}: {e}")
            await asyncio.sleep(2)

async def parallel_download(url, filename, headers, status_msg, user_id, num_connections=NUM_CONNECTIONS):
    timeout = aiohttp.ClientTimeout(total=None, sock_read=60, sock_connect=30)
    connector = aiohttp.TCPConnector(limit=num_connections + 4, ssl=False, force_close=False)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # HEAD request to check size + range support
        total_size = 0
        accept_ranges = ''
        try:
            async with session.head(url, headers=headers, allow_redirects=True) as head_resp:
                total_size = int(head_resp.headers.get('content-length', 0))
                accept_ranges = head_resp.headers.get('accept-ranges', '').lower()
        except Exception:
            pass

        # If HEAD fails, try GET with Range: 0-0 to probe
        if total_size == 0:
            probe_headers = headers.copy()
            probe_headers['Range'] = 'bytes=0-0'
            async with session.get(url, headers=probe_headers, allow_redirects=True) as probe_resp:
                content_range = probe_resp.headers.get('content-range', '')
                if content_range and '/' in content_range:
                    total_size = int(content_range.split('/')[-1])
                    accept_ranges = 'bytes'

        if total_size == 0:
            raise Exception("Could not determine file size")

        if accept_ranges != 'bytes':
            print("⚠️ Server doesn't support Range. Single connection fallback.")
            num_connections = 1

        # Pre-allocate file
        async with aiofiles.open(filename, 'wb') as f:
            await f.truncate(total_size)

        # Split into chunks
        chunk_size = total_size // num_connections
        ranges = []
        for i in range(num_connections):
            start = i * chunk_size
            end = start + chunk_size - 1 if i < num_connections - 1 else total_size - 1
            ranges.append((start, end))

        progress_tracker = {'downloaded': 0, 'done': False}
        start_time = time.time()

        async def update_progress():
            while not progress_tracker['done']:
                try:
                    await progress_bar(progress_tracker['downloaded'], total_size, status_msg, start_time, "Downloading", user_id)
                except Exception:
                    pass
                await asyncio.sleep(2)

        progress_task = asyncio.create_task(update_progress())

        try:
            tasks = [
                download_chunk(session, url, s, e, filename, i, headers, progress_tracker)
                for i, (s, e) in enumerate(ranges)
            ]
            await asyncio.gather(*tasks)
        finally:
            progress_tracker['done'] = True
            progress_task.cancel()
            try:
                await progress_task
            except (asyncio.CancelledError, Exception):
                pass

        await progress_bar(total_size, total_size, status_msg, start_time, "Downloading", user_id)
        return total_size

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text(
        "Hello! Terabox link ayachu tharu. Multi-connection parallel download-il super fast aayi file ayachu tharam! 🚀🍿\n\n"
        f"⚡ Connections: `{NUM_CONNECTIONS}` parallel threads"
    )

DOMAINS_REGEX = r"(terabox\.app|teraboxshare\.com|terabox\.com|1024terabox\.com|teraboxlink\.com|terasharefile\.com|terafileshare\.com|terasharelink\.com)"

@app.on_message(filters.text & filters.regex(DOMAINS_REGEX))
async def handle_terabox_link(client, message: Message):
    user_id = message.from_user.id

    if user_id in active_tasks:
        await message.reply_text("❌ നിന്റെ ഒരു ടാസ്ക് ഓൾറെഡി നടക്കുന്നുണ്ട്. അത് കഴിയുകയോ Cancel ചെയ്യുകയോ ചെയ്യുക!")
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
            await status_msg.edit_text("❌ Auth Token generate cheyyan pattilla! Koyeb-il REFRESH_TOKEN check cheyyu.")
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
                        print("⚠️ Token expired. Refreshing...")
                        token = await get_valid_token(force_refresh=True)
                    else:
                        await status_msg.edit_text(f"❌ API error! Status: {response.status}")
                        delete_status = False
                        return

        if not api_success:
            await status_msg.edit_text("❌ Token refresh cheythittum login failed. Refresh Token maariyittundakam!")
            delete_status = False
            return

        files = data.get("files", [])
        if not files:
            await status_msg.edit_text("❌ Ee link-il files onnum kandilla.")
            delete_status = False
            return

        file_data = files[0]
        dlink = file_data.get("dlink")
        filename = file_data.get("filename", "video.mp4")

        if not dlink:
            await status_msg.edit_text("❌ Direct download link generate cheyyan pattiyilla.")
            delete_status = False
            return

        # --- PARALLEL DOWNLOAD ---
        await status_msg.edit_text(f"⬇️ Multi-connection download start cheyyunnu... ({NUM_CONNECTIONS} threads)")

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
            await parallel_download(dlink, filename, download_headers, status_msg, user_id, num_connections=NUM_CONNECTIONS)
        except Exception as e:
            await status_msg.edit_text(f"❌ **Download Failed!**\n`{str(e)}`\n\nലിങ്ക് മാറ്റി നോക്കുക.")
            delete_status = False
            return

        # FILE SIZE SANITY CHECK
        if os.path.exists(filename) and os.path.getsize(filename) < 50 * 1024:
            try:
                async with aiofiles.open(filename, mode='r', errors='ignore') as f:
                    error_content = await f.read()
                await status_msg.edit_text(f"❌ **Terabox Error:**\nServer video-yk pakaram error message aan tannath.\n\n`{error_content[:150]}`")
            except Exception:
                await status_msg.edit_text("❌ **Terabox Error:** Corrupted file.")
            delete_status = False
            if os.path.exists(filename):
                os.remove(filename)
            return

        # UPLOAD
        await status_msg.edit_text("⬆️ Telegram-lekk upload cheyyunnu...")
        upload_start_time = time.time()

        await message.reply_video(
            video=filename,
            caption=f"**Title:** `{filename}`\n\nDownloaded via Bot 🚀",
            supports_streaming=True,
            progress=progress_bar,
            progress_args=(status_msg, upload_start_time, "Uploading", user_id)
        )

    except asyncio.CancelledError:
        await message.reply_text("🛑 **Process User poornnamayum Cancel cheythirikkunnu!**")
    except Exception as e:
        await message.reply_text(f"❌ Oru error vannu: {str(e)}")
    finally:
        active_tasks.pop(user_id, None)
        last_progress_text.pop(user_id, None)
        if filename and os.path.exists(filename):
            os.remove(filename)

        if delete_status:
            try:
                await status_msg.delete()
            except Exception:
                pass

# --- CANCEL BUTTON ---
@app.on_callback_query(filters.regex(r"^cancel_(\d+)"))
async def cancel_callback(client, callback_query: CallbackQuery):
    target_user_id = int(callback_query.data.split("_")[1])
    if callback_query.from_user.id != target_user_id:
        await callback_query.answer("❌ Ith ninte task alla!", show_alert=True)
        return

    task = active_tasks.get(target_user_id)
    if task:
        task.cancel()
        await callback_query.answer("🛑 Process Cancel cheyyunnu...")
    else:
        await callback_query.answer("⚠️ Task active alla.", show_alert=True)

if __name__ == "__main__":
    app.run()
