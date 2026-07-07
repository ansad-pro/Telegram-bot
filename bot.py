import os
import time
import math
import urllib.parse
import aiohttp
import aiofiles
from pyrogram import Client, filters
from pyrogram.types import Message

# Koyeb Environment Variables-il ninnu details edukkarulla setup
API_ID = os.environ.get("API_ID")        
API_HASH = os.environ.get("API_HASH")    
BOT_TOKEN = os.environ.get("BOT_TOKEN")  
AUTH_TOKEN = os.environ.get("AUTH_TOKEN") 

app = Client("terabox_bot", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

# Readable Format-lekku size maattan ulla function
def format_size(bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024

# Live Progress Bar function (Download-num Upload-num ithu use cheyyam)
async def progress_bar(current, total, status_msg, start_time, action="Processing"):
    if not total:
        return
    
    now = time.time()
    diff = now - start_time
    
    # 3 seconds gap-il maathrame Telegram-lekku update ayakku (To avoid flood wait)
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
        
        try:
            await status_msg.edit_text(progress_str)
        except Exception:
            pass

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("Hello! Terabox link ayachu tharu. Live progress bar ood koodi super fast aayi download cheyth file ayachu tharam! 🚀🍿")

@app.on_message(filters.text & filters.regex(r"(terabox\.com|1024terabox\.com|teraboxapp\.com)"))
async def handle_terabox_link(client, message: Message):
    url = message.text
    status_msg = await message.reply_text("🔍 Terabox link check cheyyunnu...")
    filename = None

    try:
        # 1. API-lekku Request ayakkunnu
        encoded_url = urllib.parse.quote(url)
        api_url = f"https://api.tera-peek.in/api/resolve?url={encoded_url}&mode=stream"
        
        headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers) as response:
                if response.status != 200:
                    await status_msg.edit_text(f"❌ API error! Status code: {response.status}")
                    return
                
                data = await response.json()
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

        # 2. HIGH-SPEED DOWNLOAD PROCESS (Live Progress bar)
        await status_msg.edit_text("⬇️ Downloading start cheyyunnu...")
        start_time = time.time()
        current_downloaded = 0
        
        async with aiohttp.ClientSession() as session:
            async with session.get(dlink) as resp:
                if resp.status == 200:
                    total_size = int(resp.headers.get('content-length', 0))
                    
                    # 5MB chunk sizes complex files-nu speed kootum
                    async with aiofiles.open(filename, mode='wb') as f:
                        async for chunk in resp.content.iter_chunked(5 * 1024 * 1024): 
                            await f.write(chunk)
                            current_downloaded += len(chunk)
                            await progress_bar(current_downloaded, total_size, status_msg, start_time, action="Downloading")
                else:
                    await status_msg.edit_text("❌ Terabox server-il ninnu file download cheyyan pattiyilla.")
                    return

        # 3. HIGH-SPEED UPLOAD PROCESS (Live Progress Bar)
        await status_msg.edit_text("⬆️ Telegram-lekku upload cheyyunnu...")
        upload_start_time = time.time()
        
        await message.reply_video(
            video=filename,
            caption=f"**Title:** `{filename}`\n\nDownloaded via Bot 🚀",
            supports_streaming=True,
            progress=progress_bar, 
            progress_args=(status_msg, upload_start_time, "Uploading")
        )

    except Exception as e:
        await message.reply_text(f"❌ Oru error vannu: {str(e)}")
    
    finally:
        # 4. Storage Auto-Delete (Error vannalum file delete aavum)
        if filename and os.path.exists(filename):
            os.remove(filename)
        try:
            await status_msg.delete()
        except Exception:
            pass

if __name__ == "__main__":
    app.run()

