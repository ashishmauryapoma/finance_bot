"""
Telegram Finance Management Bot
- Local dev:  python bot.py  → polling mode
- Render.com: gunicorn bot:flask_app --workers 1 --worker-class sync --timeout 120
              Set WEBHOOK_URL env var to activate webhook mode
"""

import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from dotenv import load_dotenv

from groq_handler import extract_transaction
from sheets_handler import (
    append_transaction, get_recent_transactions,
    get_summary, get_balance, rebuild_summary,
)
from auth import verify_password, is_authenticated, set_authenticated
from utils import format_summary, format_recent

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_PASSWORD = 1
_IST = timezone(timedelta(hours=5, minutes=30))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set.")

ptb_app: Application = Application.builder().token(TOKEN).build()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ist_now() -> datetime:
    return datetime.now(tz=_IST)


def _build_row(transaction: dict, username: str) -> dict:
    now = _ist_now()
    return {
        "date":      now.strftime("%d-%m-%Y"),
        "timestamp": now.strftime("%I:%M:%S %p"),
        "type":      transaction.get("type", "expense"),
        "category":  transaction.get("category", "Other"),
        "amount":    transaction.get("amount", 0),
        "note":      transaction.get("note", ""),
        "user":      username,
    }


def _format_saved(row: dict) -> str:
    type_label = "💸 Expense" if row["type"] == "expense" else "💰 Income"
    return (
        f"✅ *Transaction Saved!*\n"
        f"{'─' * 28}\n"
        f"📅 *Date:*      {row['date']}\n"
        f"💱 *Type:*      {type_label}\n"
        f"📂 *Category:* {row['category']}\n"
        f"💵 *Amount:*   ₹{row['amount']:,.2f}\n"
        f"📝 *Note:*      {row['note']}\n"
        f"{'─' * 28}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auth handlers
# ─────────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    name    = update.effective_user.first_name or "there"

    if is_authenticated(user_id):
        await update.message.reply_text(
            f"👋 Welcome back, *{name}*!\n\n"
            "Just tell me what you spent or earned and I'll save it.\n\n"
            "🔧 *Commands:*\n"
            "/recent — Last 10 transactions\n"
            "/summary — Monthly summary\n"
            "/balance — Balance details\n"
            "/logout — Log out\n"
            "/help — Help",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"🔒 This bot is password-protected.\n"
        "Please enter the *password* to continue:",
        parse_mode="Markdown",
    )
    return WAITING_PASSWORD


async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    entered = update.message.text.strip()

    # Always delete the password message to keep it out of chat history
    try:
        await update.message.delete()
    except Exception:
        pass  # silently ignore if bot lacks delete permission

    if verify_password(entered):
        set_authenticated(user_id, True)
        await update.effective_chat.send_message(
            "🔓 *Access granted!* Welcome Ashish.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await update.effective_chat.send_message(
        "❌ *Wrong password.* Please try again:",
        parse_mode="Markdown",
    )
    return WAITING_PASSWORD


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    set_authenticated(user_id, False)
    await update.message.reply_text(
        "👋 Logged out. Use /start to log in again."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main message handler — parse and save immediately, no buttons
# ─────────────────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = str(update.effective_user.id)
    username = (
        update.effective_user.username
        or update.effective_user.first_name
        or "Unknown"
    )

    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start and log in first.")
        return

    text = update.message.text.strip()
    if not text:
        return

    await update.message.reply_chat_action("typing")

    try:
        transaction = await extract_transaction(text)

        if not transaction:
            await update.message.reply_text(
                "🤔 Couldn't understand that as a transaction. Please try again."
            )
            return

        row = _build_row(transaction, username)
        append_transaction(row)

        await update.message.reply_text(
            _format_saved(row),
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"handle_message error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")


# ─────────────────────────────────────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────────────────────────────────────

async def recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return
    await update.message.reply_text("⏳ Fetching recent transactions...")
    try:
        rows = get_recent_transactions(user_id)
        await update.message.reply_text(format_recent(rows), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Recent error: {e}")
        await update.message.reply_text("⚠️ Could not fetch. Try again later.")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return
    await update.message.reply_text("⏳ Calculating summary...")
    try:
        data = get_summary(user_id)
        await update.message.reply_text(format_summary(data), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Summary error: {e}")
        await update.message.reply_text("⚠️ Could not fetch. Try again later.")


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return
    await update.message.reply_text("⏳ Calculating balance...")
    try:
        data           = get_balance(user_id)
        net_all        = data["net_balance"]
        net_month      = data["month_net"]
        net_all_icon   = "🟢" if net_all   >= 0 else "🔴"
        net_month_icon = "🟢" if net_month >= 0 else "🔴"
        msg = (
            f"💰 *Balance — {data['month']}*\n\n"
            f"📅 *This Month*\n"
            f"  Income  : ₹{data['month_income']:,.2f}\n"
            f"  Expense : ₹{data['month_expense']:,.2f}\n"
            f"  {net_month_icon} Net : ₹{net_month:,.2f}\n\n"
            f"📊 *All Time*\n"
            f"  Income  : ₹{data['all_income']:,.2f}\n"
            f"  Expense : ₹{data['all_expense']:,.2f}\n"
            f"  {net_all_icon} Balance : ₹{net_all:,.2f}\n\n"
            f"🏷️ *Top Spend This Month*\n"
            f"  {data['top_category']} — ₹{data['top_cat_amount']:,.2f}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Balance error: {e}")
        await update.message.reply_text("⚠️ Could not fetch. Try again later.")


async def fix_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return
    await update.message.reply_text("🔄 Rebuilding summary sheet...")
    try:
        rebuild_summary()
        await update.message.reply_text("✅ Summary rebuilt!")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Failed: {e}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 *Finance Bot — Help*\n\n"
        "Just type any transaction naturally and it gets saved instantly.\n\n"
        "/recent — Last 10 entries\n"
        "/summary — Monthly summary\n"
        "/balance — Balance details\n"
        "/fix — Rebuild summary sheet\n"
        "/logout — Log out\n"
        "/help — This message",
        parse_mode="Markdown",
    )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Use /help.")


# ─────────────────────────────────────────────────────────────────────────────
# Register handlers
# ─────────────────────────────────────────────────────────────────────────────

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        WAITING_PASSWORD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password)
        ],
    },
    fallbacks=[CommandHandler("start", start)],
    per_message=False,
)

ptb_app.add_handler(conv)
ptb_app.add_handler(CommandHandler("logout",  logout))
ptb_app.add_handler(CommandHandler("recent",  recent))
ptb_app.add_handler(CommandHandler("summary", summary))
ptb_app.add_handler(CommandHandler("balance", balance))
ptb_app.add_handler(CommandHandler("fix",     fix_summary))
ptb_app.add_handler(CommandHandler("help",    help_command))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
ptb_app.add_handler(MessageHandler(filters.COMMAND, unknown))

# ─────────────────────────────────────────────────────────────────────────────
# Event loop — shared for webhook mode
# ─────────────────────────────────────────────────────────────────────────────

_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)
_loop.run_until_complete(ptb_app.initialize())
logger.info("PTB app initialised.")

# ─────────────────────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────────────────────

flask_app = Flask(__name__)


@flask_app.get("/")
def health():
    return jsonify({"status": "ok", "service": "telegram-finance-bot"})


@flask_app.post("/webhook")
def webhook():
    try:
        payload = request.get_json(force=True)
        update  = Update.de_json(payload, ptb_app.bot)
        _loop.run_until_complete(ptb_app.process_update(update))
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
    return jsonify({"ok": True})


@flask_app.get("/set_webhook")
def set_webhook():
    url = os.getenv("WEBHOOK_URL", "").rstrip("/")
    if not url:
        return jsonify({"error": "WEBHOOK_URL not set"}), 400
    full = f"{url}/webhook"
    _loop.run_until_complete(ptb_app.bot.set_webhook(url=full))
    return jsonify({"ok": True, "webhook_url": full})


@flask_app.get("/delete_webhook")
def delete_webhook():
    _loop.run_until_complete(ptb_app.bot.delete_webhook())
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# Local dev — polling mode
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if os.getenv("WEBHOOK_URL"):
        port = int(os.getenv("PORT", 8080))
        logger.info(f"Webhook mode on port {port}")
        flask_app.run(host="0.0.0.0", port=port)
    else:
        logger.info("Polling mode")
        _loop.run_until_complete(ptb_app.shutdown())
        ptb_app.run_polling(allowed_updates=Update.ALL_TYPES)
