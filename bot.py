import os
import time
import math
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

# ബാക്ക്ഗ്രൗണ്ടിൽ ഓട്ടോമാറ്റിക് ആയി അപ്ഡേറ്റ് ആകുന്ന വേരിയബിൾ
CURRENT_AUTH_TOKEN = None

app = Client("terabox_bot", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)
active_tasks = {}

# --- FAKE PORT SERVER FOR KOYEB TIMEOUT FIX ---
def run_dummy_server():
    try:
        port = int(os.environ.get("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
        print(f"ℹ️ Fake Port Server started on port {port}")
        server.serve_forever()
    except Exception as e:
        print(f"❌ Dummy server error: {e}")

threading.Thread(target=run_dummy_server, daemon=True).start()
# -----------------------------------------------

# --- AUTOMATIC FIREBASE TOKEN REFRESH FUNCTION ---
async def get_valid_token(force_refresh=False):
    global CURRENT_AUTH_TOKEN
    
    if not REFRESH_TOKEN:
        print("❌ ERROR: REFRESH_TOKEN is not set in Koyeb environment variables!")
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
# --------------------------------------------------

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
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel Process", callback_data=f"cancel_{user_id}")]
        ])
        try:
            await status_msg.edit_text(progress_str, reply_markup=reply_markup)
        except Exception:
            pass

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("Hello! Terabox link ayachu tharu. Live progress bar ood koodi super fast aayi download cheyth file ayachu tharam! 🚀🍿")

DOMAINS_REGEX = r"(terabox\.app|teraboxshare\.com|terabox\.com|1024terabox\.com|teraboxlink\.com|terasharefile\.com|terafileshare\.com|terasharelink\.com)"

@app.on_message(filters.text & filters.regex(DOMAINS_REGEX))
async def handle_terabox_link(client, message: Message):
    user_id = message.from_user.id
    
    if user_id in active_tasks:
        await message.reply_text("❌ നിന്റെ ഒരു ടാസ്ക് ഓൾറെഡി നടക്കുന്നുണ്ട്. അത് കഴിയുകയോ അല്ലെങ്കിൽ Cancel ചെയ്യുകയോ ചെയ്യുക!")
        return

    status_msg = await message.reply_text("🔍 Terabox link check cheyyunnu...")
    filename = None
    active_tasks[user_id] = asyncio.current_task()

    try:
        url = message.text
        encoded_url = urllib.parse.quote(url)
        api_url = f"https://api.tera-peek.in/api/resolve?url={encoded_url}&mode=stream"
        
        # ഓട്ടോമാറ്റിക് ടോക്കൺ എടുക്കുന്നു
        token = await get_valid_token()
        if not token:
            await status_msg.edit_text("❌ Authentication Token ജനറേറ്റ് ചെയ്യാൻ പറ്റിയില്ല! Koyeb-ൽ REFRESH_TOKEN ചെക്ക് ചെയ്യുക.")
            return

        api_success = False
        data = None

        # API Request അയക്കുന്നു (ടോക്കൺ എക്സ്പെയർ ആയാൽ റിഫ്രഷ് ചെയ്യാനുള്ള ലോജിക്)
        for attempt in range(2): 
            headers = {"Authorization": f"Bearer {token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        api_success = True
                        break
                    elif response.status in [401, 403] and attempt == 0:
                        print("⚠️ Token expired during request. Refreshing now...")
                        token = await get_valid_token(force_refresh=True)
                    else:
                        await status_msg.edit_text(f"❌ API error! Status code: {response.status}")
                        return

        if not api_success:
            await status_msg.edit_text("❌ Token refresh ചെയ്തിട്ടും ലോഗിൻ പരാജയപ്പെട്ടു. Refresh Token മാറിയിട്ടുണ്ടാകാം!")
            return

        files = data.get("files", [])
        if not files:
            await status_msg.edit_text("❌ Ee link-il files onnum kandilla.")
            return
        
        file_data = files[0]
        dlink = file_data.get("dlink")
        filename = file_data.get("filename", "video.mp4")

        if not dlink:
            await status_msg.edit_text("❌ Direct download link generate cheyyan pattiyilla.")
            return

        # 2. DOWNLOAD PROCESS
        await status_msg.edit_text("⬇️ Downloading start cheyyunnu...")
        start_time = time.time()
        current_downloaded = 0
        
        # Mobile Chrome User Agent + Referer Added for bypassing 80MB Throttling
        download_headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Referer": "https://www.terabox.com/"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(dlink, headers=download_headers) as resp:
                if resp.status == 200:
                    total_size = int(resp.headers.get('content-length', 0))
                    async with aiofiles.open(filename, mode='wb') as f:
                        # 1MB Chunks for smooth large file flow
                        async for chunk in resp.content.iter_chunked(1024 * 1024): 
                            await f.write(chunk)
                            current_downloaded += len(chunk)
                            await progress_bar(current_downloaded, total_size, status_msg, start_time, "Downloading", user_id)
                else:
                    await status_msg.edit_text(f"❌ Terabox server error. Status: {resp.status}")
                    return

        # 3. UPLOAD PROCESS
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
        await message.reply_text("🛑 **Process User പൂർണ്ണമായും Cancel ചെയ്തിരിക്കുന്നു!**")
    except Exception as e:
        await message.reply_text(f"❌ Oru error vannu: {str(e)}")
    finally:
        active_tasks.pop(user_id, None)
        if filename and os.path.exists(filename):
            os.remove(filename)
        try:
            await status_msg.delete()
        except Exception:
            pass

# --- CANCEL BUTTON CLICK HANDLER ---
@app.on_callback_query(filters.regex(r"^cancel_(\d+)"))
async def cancel_callback(client, callback_query: CallbackQuery):
    target_user_id = int(callback_query.data.split("_")[1])
    if callback_query.from_user.id != target_user_id:
        await callback_query.answer("❌ ഇത് നിന്റെ ടാസ്ക് അല്ല, നിനക്ക് ക്യാൻസൽ ചെയ്യാൻ പറ്റില്ല!", show_alert=True)
        return
        
    task = active_tasks.get(target_user_id)
    if task:
        task.cancel()
        await callback_query.answer("🛑 Process Cancel ചെയ്യുന്നു...")
    else:
        await callback_query.answer("⚠️ ടാസ്ക് നിലവിൽ സജീവമല്ല അല്ലെങ്കിൽ കഴിഞ്ഞുപോയി.", show_alert=True)

if __name__ == "__main__":
    app.run()
