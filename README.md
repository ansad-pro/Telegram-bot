# Terabox Downloader Telegram Bot 🚀
A powerful, high-speed Telegram bot designed to bypass standard limits and download videos/files from Terabox links, uploading them directly back to Telegram. Powered by **Pyrogram (MTProto)** and the **Tera-Peek API**.
## ✨ Features
- **High-Speed Downloads & Uploads:** Optimized with `tgcrypto` and 5MB chunk streaming for maximum performance.
- **Live Progress Bar:** Shows real-time download/upload speed, percentage, file size, and ETA (Time Remaining) without hitting Telegram flood waits.
- **Large File Support:** Supports downloading and uploading files up to **2 GB** smoothly (No 50MB bot API limit).
- **Auto-Clean Storage:** Automatically clears temporary files from the server after successful upload or failure, ensuring 100% disk safety.
## 🛠️ Environment Variables
To run this bot safely, you must configure the following Environment Variables on your hosting provider (e.g., Koyeb). **Do NOT expose these in a public `.env` file on GitHub.**

| Variable | Description |
| :--- | :--- |
| `API_ID` | Your Telegram API ID from [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | Your Telegram API Hash from [my.telegram.org](https://my.telegram.org) |
| `BOT_TOKEN` | Your Telegram Bot Token from [@BotFather](https://t.me/BotFather) |
| `AUTH_TOKEN` | Your Bearer Authorization Token from [tera-peek.in](https://tera-peek.in) |

## 🚀 Deployment (Koyeb)
1. Create a repository on GitHub and upload `bot.py` and `requirements.txt`.
2. Go to [Koyeb Dashboard](https://app.koyeb.com/) and create a new Web/Worker Service.
3. Connect your GitHub repository.
4. Add the **Environment Variables** listed above in the Koyeb configuration section.
5. Set the Run Command:
   ```bash
   python bot.py



   
