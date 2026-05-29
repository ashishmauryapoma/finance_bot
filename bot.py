"""
Telegram Finance Management Bot
- Local dev:  runs in polling mode (no webhook needed)
- Render.com: runs as Flask web service with Telegram webhook
              Set WEBHOOK_URL env var to your Render app URL to activate webhook mode
"""

import os
import asyncio
import logging
from datetime import datetime

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
from sheets_handler import append_transaction, get_recent_transactions, get_summary
from auth import verify_password, is_authenticated, set_authenticated
from utils import format_confirmation, format_summary, format_recent

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_PASSWORD = 1

# ── Flask app (used in webhook / web-service mode) ────────────────────────────
flask_app = Flask(__name__)
_ptb_app: Application = None


def get_ptb_app() -> Application:
    global _ptb_app
    if _ptb_app is None:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set.")
        _ptb_app = Application.builder().token(token).build()
        _register_handlers(_ptb_app)
        logger.info("PTB application initialised")
    return _ptb_app


# ─────────────────────────────────────────────────────────────────────────────
# Telegram command / message handlers
# ─────────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    name = update.effective_user.first_name or "there"

    if is_authenticated(user_id):
        await update.message.reply_text(
            f"👋 Welcome back, *{name}*!\n\n"
            "I'm your personal finance assistant. Just tell me what you spent or earned.\n\n"
            "📝 *Examples:*\n"
            "• `Spent 500 on petrol`\n"
            "• `Received 10000 salary`\n"
            "• `Paanch sau ka khana khaya`\n"
            "• `Paid 1200 for electricity bill`\n\n"
            "🔧 *Commands:*\n"
            "/recent — Last 10 transactions\n"
            "/summary — Monthly summary\n"
            "/logout — Log out\n"
            "/help — Help",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"🔐 Welcome, *{name}*!\n\n"
            "This bot is password-protected.\n"
            "Please enter the *password* to continue:",
            parse_mode="Markdown",
        )
        return WAITING_PASSWORD


async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    entered = update.message.text.strip()

    if verify_password(entered):
        set_authenticated(user_id, True)
        await update.message.reply_text(
            "✅ *Access granted!* Welcome aboard.\n\n"
            "Just send me any financial transaction in plain language — "
            "English or Hindi, I understand both!\n\n"
            "📝 *Try:*\n"
            "• `Spent 500 on petrol`\n"
            "• `1000 rupay grocery mein gaye`\n"
            "• `Received 5000 from client`",
            parse_mode="Markdown",
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "❌ *Wrong password.* Please try again:",
            parse_mode="Markdown",
        )
        return WAITING_PASSWORD


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    set_authenticated(user_id, False)
    await update.message.reply_text(
        "👋 Logged out successfully. Use /start to log in again."
    )


async def recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start and enter the password first.")
        return
    await update.message.reply_text("⏳ Fetching your recent transactions...")
    try:
        rows = get_recent_transactions(user_id)
        await update.message.reply_text(format_recent(rows), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Recent error: {e}")
        await update.message.reply_text("⚠️ Could not fetch transactions. Try again later.")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start and enter the password first.")
        return
    await update.message.reply_text("⏳ Calculating your summary...")
    try:
        data = get_summary(user_id)
        await update.message.reply_text(format_summary(data), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Summary error: {e}")
        await update.message.reply_text("⚠️ Could not fetch summary. Try again later.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 *Finance Bot — Help*\n\n"
        "*How to log a transaction:*\n"
        "Just type naturally! I understand English and Hindi.\n\n"
        "📤 *Expense examples:*\n"
        "• `Spent 500 on petrol`\n"
        "• `Paid 1200 rent`\n"
        "• `Grocery 850 rupay`\n"
        "• `200 ka chai nashta`\n\n"
        "📥 *Income examples:*\n"
        "• `Received 50000 salary`\n"
        "• `Client payment 15000`\n"
        "• `Freelance income 8000`\n\n"
        "📊 *Commands:*\n"
        "/recent — Last 10 entries\n"
        "/summary — This month's summary\n"
        "/logout — Log out of the bot\n"
        "/help — This help message",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    username = (
        update.effective_user.username
        or update.effective_user.first_name
        or "Unknown"
    )

    if not is_authenticated(user_id):
        await update.message.reply_text(
            "🔐 You need to log in first. Use /start to begin."
        )
        return

    text = update.message.text.strip()
    if not text:
        return

    await update.message.reply_chat_action("typing")

    try:
        transaction = await extract_transaction(text)

        if not transaction:
            await update.message.reply_text(
                "🤔 I couldn't understand that as a financial transaction.\n\n"
                "Try something like:\n"
                "• `Spent 500 on petrol`\n"
                "• `Received 10000 salary`\n"
                "• `1200 rupay grocery`"
            )
            return

        now = datetime.now()
        row = {
            "date": now.strftime("%Y-%m-%d"),
            "type": transaction.get("type", "expense"),
            "category": transaction.get("category", "General"),
            "amount": transaction.get("amount", 0),
            "note": transaction.get("note", text),
            "user": username,
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

        append_transaction(row)
        await update.message.reply_text(format_confirmation(row), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Handle message error for user {user_id}: {e}")
        await update.message.reply_text(
            "⚠️ Something went wrong while processing your entry.\n"
            "Please try again in a moment."
        )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Unknown command. Type /help for available options."
    )


def _register_handlers(app: Application):
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password)
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("recent", recent))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))


# ─────────────────────────────────────────────────────────────────────────────
# Flask routes  (webhook mode — used on Render free web service)
# ─────────────────────────────────────────────────────────────────────────────

@flask_app.get("/")
def health():
    """Render health-check endpoint."""
    return jsonify({"status": "ok", "service": "telegram-finance-bot"})


@flask_app.post("/webhook")
def webhook():
    """Telegram pushes every update here."""
    app = get_ptb_app()
    data = request.get_json(force=True)

    async def process():
        async with app:
            update = Update.de_json(data, app.bot)
            await app.process_update(update)

    asyncio.run(process())
    return jsonify({"ok": True})


@flask_app.get("/set_webhook")
def set_webhook():
    """
    Register the webhook with Telegram.
    Visit this URL once after deploying:
      https://<your-app>.onrender.com/set_webhook
    """
    webhook_url = os.getenv("WEBHOOK_URL", "").rstrip("/")
    if not webhook_url:
        return jsonify({"error": "WEBHOOK_URL env var not set"}), 400

    full_url = f"{webhook_url}/webhook"

    async def do_set():
        app = get_ptb_app()
        async with app:
            await app.bot.set_webhook(url=full_url)

    asyncio.run(do_set())
    logger.info(f"Webhook registered: {full_url}")
    return jsonify({"ok": True, "webhook_url": full_url})


@flask_app.get("/delete_webhook")
def delete_webhook():
    """Remove the webhook — useful when switching back to local polling."""
    async def do_delete():
        app = get_ptb_app()
        async with app:
            await app.bot.delete_webhook()

    asyncio.run(do_delete())
    return jsonify({"ok": True, "message": "Webhook deleted"})


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _run_polling():
    """Local development: classic long-polling (no server needed)."""
    logger.info("🔄 No WEBHOOK_URL set — starting in polling mode (local dev)")
    app = get_ptb_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    webhook_url = os.getenv("WEBHOOK_URL", "")

    if webhook_url:
        # Webhook / production mode
        port = int(os.getenv("PORT", 8080))
        logger.info(f"🚀 Webhook mode — Flask on port {port}")
        flask_app.run(host="0.0.0.0", port=port)
    else:
        # Polling mode — local dev
        _run_polling()
