import os
import threading
import logging
import uvicorn
import json
import uuid
import asyncio

from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# --- Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID"))
PORT = int(os.environ.get("PORT", 8080))

if not BOT_TOKEN or not ADMIN_CHAT_ID:
    raise ValueError("Error: BOT_TOKEN and ADMIN_CHAT_ID environment variables must be set.")

# --- FastAPI Web Server ---
app_api = FastAPI()

@app_api.get("/healthz")
async def healthz():
    """A simple health check endpoint."""
    return {"status": "ok"}

@app_api.post("/notify")
async def notify(request: Request):
    """
    Receives a request, stores the data, and sends a notification with a unique ID.
    """
    try:
        data = await request.json()
        log.info(f"Received request on /notify: {data}")

        request_uuid = str(uuid.uuid4())
        application = request.app.state.application
        application.bot_data[request_uuid] = data
        text = f"🚨 New Request Received:\n\nDetails: `{json.dumps(data, indent=2)}`"
        keyboard = [
            [
                InlineKeyboardButton("✅ Accept", callback_data=f"accept_{request_uuid}"),
                InlineKeyboardButton("❌ Decline", callback_data=f"decline_{request_uuid}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        bot = request.app.state.bot
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=text,
            reply_markup=reply_markup,
            parse_mode='MarkdownV2'
        )
        return {"status": "notification_sent"}
    except Exception as e:
        log.error(f"Error in /notify endpoint: {e}")
        return {"status": "error", "message": str(e)}

def start_uvicorn_in_thread(app):
    """Runs the Uvicorn server in a separate thread."""
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")

# --- Telegram Bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    await update.message.reply_text(f"Hello! Your Chat ID is: {update.effective_chat.id}")

async def request_demo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /request_demo command."""
    await update.message.reply_text("✅ Demo request received!")
    log.info(f"Demo request received from chat ID: {update.effective_chat.id}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks."""
    query = update.callback_query
    await query.answer()
    action, request_uuid = query.data.split("_", 1)
    request_data = context.bot_data.pop(request_uuid, None)
    if not request_data:
        await query.edit_message_text(text="❓ This request has already been handled or has expired.")
        return
    pretty_data = json.dumps(request_data, indent=2)
    if action == "accept":
        new_text = f"✅ Request Accepted!\n\nDetails: `{pretty_data}`"
        await query.edit_message_text(text=new_text, parse_mode='MarkdownV2')
    elif action == "decline":
        new_text = f"❌ Request Declined!\n\nDetails: `{pretty_data}`"
        await query.edit_message_text(text=new_text, parse_mode='MarkdownV2')

async def post_startup(application: Application):
    """Runs once after the bot starts, with a delay to prevent race conditions."""
    try:
        log.info("Running post_startup...")
        await application.bot.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(2) 
        await application.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text="✅ **FINAL VERSION v5** - Bot is online."
        )
        app_api.state.bot = application.bot
        app_api.state.application = application
        log.info("post_startup completed successfully.")
    except Exception as e:
        log.warning(f"Startup notify failed: {e}")

def main():
    """Main function to set up and run everything."""
    application = Application.builder().token(BOT_TOKEN).post_init(post_startup).build()
    
    # Add handlers for all commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("request_demo", request_demo))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    fastapi_thread = threading.Thread(
        target=start_uvicorn_in_thread,
        args=(app_api,),
        daemon=True
    )
    fastapi_thread.start()
    log.info("Starting Telegram bot polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
