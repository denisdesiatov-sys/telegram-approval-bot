import os
import logging
import uvicorn
import json
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
# Format: {"machine_id_1": "pending", "machine_id_2": "approved"}
approval_db = {}

# --- FastAPI Web Server ---
app_api = FastAPI()

# --- Telegram Bot Application Setup ---
# We configure the bot application but don't run it directly.
# Uvicorn will run the FastAPI app, which will in turn manage the bot.
application = Application.builder().token(BOT_TOKEN).build()


# --- FastAPI Endpoints ---
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
    """Handles incoming requests from launchers."""
    data = await request.json()
    log.info(f"Received request on /notify: {data}")
    event_type = data.get("event")
    
    if event_type == "Permission Requested":
        user_name = data.get("user", "Unknown User")
        machine_id = data.get("machine_id", "Unknown ID")
        approval_db[machine_id] = "pending"
        
        text = (
            f"❗️ New Permission Request ❗️\n\n"
            f"👤 **User:** {user_name}\n"
            f"💻 **Machine ID:** `{machine_id}`"
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{machine_id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"deny_{machine_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await application.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=text, reply_markup=reply_markup, parse_mode='MarkdownV2'
        )
        return {"status": "permission_request_received"}
    else:
        text = f"🔔 Notification:\n\n`{json.dumps(data, indent=2)}`"
        await application.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode='MarkdownV2')
        return {"status": "generic_notification_sent"}

# This is the single endpoint that Telegram will send all updates to.
@app_api.post("/telegram")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates by passing them to the bot application."""
    update_data = await request.json()
    update = Update.de_json(update_data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

# --- Bot Command and Callback Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Hello! I am the remote approval bot (v9). Your Chat ID is: {update.effective_chat.id}")

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

# Add the handlers to the application.
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_callback))

# --- Server Startup and Shutdown Events ---
@app_api.on_event("startup")
async def on_startup():
    """This function runs when the server starts. It sets the webhook."""
    log.info("Server starting up. Setting webhook...")
    await application.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram")

@app_api.on_event("shutdown")
async def on_shutdown():
    """This function runs when the server shuts down. It removes the webhook."""
    log.info("Server shutting down. Deleting webhook...")
    await application.bot.delete_webhook()

# --- Main entry point to run the server ---
if __name__ == "__main__":
    uvicorn.run(app_api, host="0.0.0.0", port=PORT)
