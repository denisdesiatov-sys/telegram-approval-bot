import os
import logging
import uvicorn
import json
import uuid
import asyncio
from fastapi import FastAPI, Request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
log = logging.getLogger(__name__)

# --- Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID"))
PORT = int(os.environ.get("PORT", 8080))
# The full URL of your Render service (e.g., https://your-app-name.onrender.com)
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if not all([BOT_TOKEN, ADMIN_CHAT_ID, WEBHOOK_URL]):
    raise ValueError("Error: BOT_TOKEN, ADMIN_CHAT_ID, and WEBHOOK_URL environment variables must be set.")

# --- Bot Setup ---
# We build the application first, so it can be used in the FastAPI app state.
application = Application.builder().token(BOT_TOKEN).build()

# --- FastAPI Web Server ---
# The web server is now the main application.
app_api = FastAPI()

@app_api.on_event("startup")
async def startup_event():
    """On startup, set the webhook and send a confirmation message."""
    try:
        log.info(f"Setting webhook to {WEBHOOK_URL}/webhook")
        await application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook", allowed_updates=Update.ALL_TYPES)
        # Give it a moment to register before sending a message
        await asyncio.sleep(2)
        await application.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text="✅ **WEBHOOK v7** - Bot is online and running in production mode."
        )
        # Store the application instance in the app's state
        app_api.state.application = application
    except Exception as e:
        log.error(f"Startup error: {e}")

@app_api.post("/webhook")
async def webhook(request: Request):
    """This endpoint receives updates from Telegram."""
    try:
        data = await request.json()
        async with application:
            await application.process_update(Update.de_json(data, application.bot))
        return Response(status_code=200)
    except Exception as e:
        log.error(f"Error in webhook: {e}")
        return Response(status_code=500)

@app_api.post("/notify")
async def notify(request: Request):
    """Receives an external request and sends a notification."""
    try:
        data = await request.json()
        log.info(f"Received request on /notify: {data}")
        request_uuid = str(uuid.uuid4())
        # Access the application instance from the app's state
        app = request.app.state.application
        app.bot_data[request_uuid] = data
        text = f"🚨 New Request Received:\n\nDetails:\n{json.dumps(data, indent=2)}"
        keyboard = [
            [
                InlineKeyboardButton("✅ Accept", callback_data=f"accept_{request_uuid}"),
                InlineKeyboardButton("❌ Decline", callback_data=f"decline_{request_uuid}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await app.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=text, reply_markup=reply_markup
        )
        return {"status": "notification_sent"}
    except Exception as e:
        log.error(f"Error in /notify endpoint: {e}")
        return {"status": "error", "message": str(e)}

# --- Telegram Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    await update.message.reply_text(f"Hello! Your Chat ID is: {update.effective_chat.id}")

async def request_demo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /request_demo command."""
    await update.message.reply_text("✅ Demo request received!")

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
        await query.edit_message_text(text=f"✅ Request Accepted!\n\nDetails:\n{pretty_data}")
    elif action == "decline":
        await query.edit_message_text(text=f"❌ Request Declined!\n\nDetails:\n{pretty_data}")

# Add all handlers to the application instance
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("request_demo", request_demo))
application.add_handler(CallbackQueryHandler(button_callback))

# The main entrypoint for the server
if __name__ == "__main__":
    uvicorn.run(app_api, host="0.0.0.0", port=PORT)
