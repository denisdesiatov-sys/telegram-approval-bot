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
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") # Required for webhook mode

if not all([BOT_TOKEN, ADMIN_CHAT_ID, WEBHOOK_URL]):
    raise ValueError("BOT_TOKEN, ADMIN_CHAT_ID, and WEBHOOK_URL must be set.")

# --- In-Memory Database for Approval Status ---
# In a real production app, you would use a database like Redis or Firestore.
# Format: {"machine_id_1": "pending", "machine_id_2": "approved"}
approval_db = {}

# --- FastAPI Web Server ---
app_api = FastAPI()

@app_api.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app_api.post("/check_status/{machine_id}")
async def check_status(machine_id: str):
    """Endpoint for the macOS launcher to poll for its approval status."""
    status = approval_db.get(machine_id, "not_found")
    log.info(f"Status check for {machine_id}: {status}")
    return {"status": status}

@app_api.post("/notify")
async def notify(request: Request):
    """Handles incoming requests from launchers or other services."""
    data = await request.json()
    log.info(f"Received request on /notify: {data}")
    event_type = data.get("event")
    
    # This is a new user asking for permission for the first time.
    if event_type == "Permission Requested":
        user_name = data.get("user", "Unknown User")
        machine_id = data.get("machine_id", "Unknown ID")
        
        # Store the request as pending.
        approval_db[machine_id] = "pending"
        
        text = (
            f"❗️ New Permission Request ❗️\n\n"
            f"👤 **User:** {user_name}\n"
            f"💻 **Machine ID:** `{machine_id}`"
        )
        # The callback_data now includes the machine_id to identify the user.
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{machine_id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"deny_{machine_id}"),
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
        return {"status": "permission_request_received"}
    
    # Handle other generic notifications (like the setup confirmation).
    else:
        text = f"🔔 Notification:\n\n`{json.dumps(data, indent=2)}`"
        bot = request.app.state.bot
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode='MarkdownV2')
        return {"status": "generic_notification_sent"}

# --- Telegram Bot (Webhook Mode) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Hello! I am the approval bot. Your Chat ID is: {update.effective_chat.id}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the admin's 'Approve' or 'Deny' clicks."""
    query = update.callback_query
    await query.answer()
    
    action, machine_id = query.data.split("_", 1)
    
    user_info = f"Request for Machine ID:\n`{machine_id}`"
    
    if action == "approve":
        approval_db[machine_id] = "approved"
        await query.edit_message_text(text=f"✅ **Approved**\n\n{user_info}", parse_mode='MarkdownV2')
    elif action == "deny":
        approval_db[machine_id] = "denied"
        await query.edit_message_text(text=f"❌ **Denied**\n\n{user_info}", parse_mode='MarkdownV2')

async def main():
    """Sets up and runs the bot in webhook mode."""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Pass the bot instance to the FastAPI app state.
    app_api.state.bot = application.bot
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Set up the webhook.
    await application.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram")
    
    # Create a custom Uvicorn server configuration.
    config = uvicorn.Config(app=application.asgi_app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    
    log.info("Starting bot and server...")
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
