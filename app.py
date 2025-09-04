import os
import logging
import uvicorn
import json
import asyncio

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler

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
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if not all([BOT_TOKEN, ADMIN_CHAT_ID, WEBHOOK_URL]):
    raise ValueError("BOT_TOKEN, ADMIN_CHAT_ID, and WEBHOOK_URL must be set.")

# --- In-Memory Database for Approval Status ---
approval_db = {}

# --- FastAPI Web Server ---
app_api = FastAPI()

# --- Telegram Bot Application Setup ---
application = Application.builder().token(BOT_TOKEN).build()


# --- FastAPI Endpoints ---
@app_api.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app_api.get("/check_status/{machine_id}")
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
            f"User: {user_name}\n"
            f"Machine ID: {machine_id}"
        )
        keyboard = [
            [
                {"text": "✅ Approve", "callback_data": f"approve_{machine_id}"},
                {"text": "❌ Deny", "callback_data": f"deny_{machine_id}"},
            ]
        ]
        await application.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=text, reply_markup={"inline_keyboard": keyboard}
        )
        return {"status": "permission_request_received"}
    else:
        text = f"🔔 Notification:\n\n{json.dumps(data, indent=2)}"
        await application.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
        return {"status": "generic_notification_sent"}

# --- THIS IS THE NEW, BULLETPROOF WEBHOOK HANDLER ---
@app_api.post("/telegram")
async def telegram_webhook(request: Request):
    """
    This function handles all incoming updates from Telegram and now includes
    robust error logging.
    """
    global approval_db
    update_data = await request.json()
    log.info(f"--- Raw Telegram Data Received: {update_data}")

    try:
        # Check if this is a button press (a callback_query)
        if "callback_query" in update_data:
            log.info("--- Processing a button press (callback_query)...")
            callback_query = update_data["callback_query"]
            callback_data = callback_query["data"]
            message_id = callback_query["message"]["message_id"]
            chat_id = callback_query["message"]["chat"]["id"]
            
            # Acknowledge the button press to stop the "Loading..." spinner
            await application.bot.answer_callback_query(callback_query_id=callback_query["id"])
            log.info("--- Acknowledged button press.")
            
            action, machine_id = callback_data.split("_", 1)
            user_info = f"Request for Machine ID: {machine_id}"
            
            if action == "approve":
                log.info(f"--- Action is 'approve' for machine_id: {machine_id}")
                approval_db[machine_id] = "approved"
                await application.bot.edit_message_text(text=f"✅ Approved\n\n{user_info}", chat_id=chat_id, message_id=message_id)
                log.info(f"--- Successfully set status to 'approved' for {machine_id}.")
            elif action == "deny":
                log.info(f"--- Action is 'deny' for machine_id: {machine_id}")
                approval_db[machine_id] = "denied"
                await application.bot.edit_message_text(text=f"❌ Denied\n\n{user_info}", chat_id=chat_id, message_id=message_id)
                log.info(f"--- Successfully set status to 'denied' for {machine_id}.")
                
        # Check if it's a regular command message
        elif "message" in update_data and "text" in update_data["message"]:
            log.info("--- Processing a text command...")
            message = update_data["message"]
            chat_id = message["chat"]["id"]
            text = message["text"]
            
            if text == "/start":
                await application.bot.send_message(chat_id=chat_id, text=f"Hello! I am the remote approval bot (v18-bulletproof). Your Chat ID is: {chat_id}")
            elif text == "/clear_cache" and chat_id == ADMIN_CHAT_ID:
                approval_db.clear()
                await application.bot.send_message(chat_id=chat_id, text="✅ Server cache cleared.")
                log.info("Approval cache cleared by admin.")

    except Exception as e:
        # If anything goes wrong, log the exact error.
        log.error(f"--- !!! CRITICAL ERROR processing update: {e}", exc_info=True)

    return {"status": "ok"}


# --- Server Startup and Shutdown Events ---
@app_api.on_event("startup")
async def on_startup():
    log.info("Server starting up...")
    await application.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram")

@app_api.on_event("shutdown")
async def on_shutdown():
    log.info("Server shutting down...")
    await application.bot.delete_webhook()

if __name__ == "__main__":
    uvicorn.run(app_api, host="0.0.0.0", port=PORT)
```
