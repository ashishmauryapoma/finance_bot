"""
Telegram Finance Management Bot
- Local dev:  python bot.py  → polling mode (no server needed)
- Render.com: gunicorn bot:flask_app → webhook mode (free web service)
              Activated when WEBHOOK_URL env var is set
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from dotenv import load_dotenv

from groq_handler import extract_transaction, EXPENSE_CATEGORIES, INCOME_CATEGORIES
from sheets_handler import append_transaction, get_recent_transactions, get_summary, get_balance, rebuild_summary
from auth import verify_password, is_authenticated, set_authenticated
from utils import format_summary, format_recent

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Conversation states
# ─────────────────────────────────────────────────────────────────────────────

WAITING_PASSWORD = 1

# Edit sub-states
EDIT_CHOOSE_FIELD = 10
EDIT_TYPE         = 11
EDIT_CATEGORY     = 12
EDIT_AMOUNT       = 13
EDIT_NOTE         = 14

# IST timezone
_IST = timezone(timedelta(hours=5, minutes=30))

# ─────────────────────────────────────────────────────────────────────────────
# Build PTB Application
# ─────────────────────────────────────────────────────────────────────────────

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


def _format_card(row: dict) -> str:
    """Build the transaction confirmation card text."""
    type_label = "💸 Expense" if row["type"] == "expense" else "💰 Income"
    cat_emoji  = "📂"
    return (
        f"📤 *Transaction Preview*\n"
        f"{'─' * 28}\n"
        f"📅 *Date:*     {row['date']}\n"
        f"💱 *Type:*     {type_label}\n"
        f"{cat_emoji} *Category:* {row['category']}\n"
        f"💵 *Amount:*  ₹{row['amount']:,.2f}\n"
        f"📝 *Note:*     {row['note']}\n"
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
            "I'm your personal finance assistant. Just tell me what you spent or earned.\n\n"
            "🔧 *Commands:*\n"
            "/recent — Last 10 transactions\n"
            "/summary — Monthly summary\n"
            "/balance — Remaining balance details\n"
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
            "English or Hindi, I understand both!",
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


# ─────────────────────────────────────────────────────────────────────────────
# Main message handler — extract → show card with buttons
# ─────────────────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = str(update.effective_user.id)
    username = (
        update.effective_user.username
        or update.effective_user.first_name
        or "Unknown"
    )

    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 You need to log in first. Use /start to begin.")
        return

    text = update.message.text.strip()
    if not text:
        return

    await update.message.reply_chat_action("typing")

    try:
        transaction = await extract_transaction(text)

        if not transaction:
            await update.message.reply_text(
                "🤔 I couldn't understand that as a financial transaction. Please try again."
            )
            return

        row = _build_row(transaction, username)

        # Store pending transaction in user_data until Submit is pressed
        context.user_data["pending_txn"] = row
        context.user_data["username"]    = username

        await update.message.reply_text(
            _format_card(row),
            parse_mode="Markdown",
            reply_markup=_confirm_keyboard(),
        )

    except Exception as e:
        logger.error(f"handle_message error for {user_id}: {e}")
        await update.message.reply_text(
            "⚠️ Something went wrong while processing your entry. Please try again."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Callback query handler — Submit / Edit buttons
# ─────────────────────────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = str(query.from_user.id)
    data    = query.data

    await query.answer()   # removes the loading spinner on the button

    if not is_authenticated(user_id):
        await query.edit_message_text("🔐 Session expired. Please /start again.")
        return

    row = context.user_data.get("pending_txn")

    # ── Submit ────────────────────────────────────────────────────────────────
    if data == "txn_submit":
        if not row:
            await query.edit_message_text("⚠️ No pending transaction found. Please send it again.")
            return
        try:
            append_transaction(row)
            type_label = "💸 Expense" if row["type"] == "expense" else "💰 Income"
            await query.edit_message_text(
                f"📤 *Transaction Recorded!*\n"
                f"{'─' * 28}\n"
                f"📅 *Date:*     {row['date']}\n"
                f"💱 *Type:*     {type_label}\n"
                f"📂 *Category:* {row['category']}\n"
                f"💵 *Amount:*  ₹{row['amount']:,.2f}\n"
                f"📝 *Note:*     {row['note']}\n"
                f"{'─' * 28}\n\n"
                f"✅ *Saved to Google Sheets!*",
                parse_mode="Markdown",
            )
            context.user_data.pop("pending_txn", None)
        except Exception as e:
            logger.error(f"Submit error: {e}")
            await query.edit_message_text("⚠️ Failed to save. Please try again.")

    # ── Edit — show field chooser ─────────────────────────────────────────────
    elif data == "txn_edit":
        await query.edit_message_text(
            _format_card(row) + "\n\n*What would you like to edit?*",
            parse_mode="Markdown",
            reply_markup=_edit_field_keyboard(),
        )

    # ── Back to confirm card ──────────────────────────────────────────────────
    elif data == "edit_back":
        await query.edit_message_text(
            _format_card(row),
            parse_mode="Markdown",
            reply_markup=_confirm_keyboard(),
        )

    # ── Edit Type — show inline buttons ──────────────────────────────────────
    elif data == "edit_type":
        await query.edit_message_text(
            _format_card(row) + "\n\n*Select the transaction type:*",
            parse_mode="Markdown",
            reply_markup=_type_keyboard(),
        )

    elif data == "set_type_expense":
        row["type"] = "expense"
        context.user_data["pending_txn"] = row
        await query.edit_message_text(
            _format_card(row) + "\n\n*Type updated! What else?*",
            parse_mode="Markdown",
            reply_markup=_edit_field_keyboard(),
        )

    elif data == "set_type_income":
        row["type"] = "income"
        context.user_data["pending_txn"] = row
        await query.edit_message_text(
            _format_card(row) + "\n\n*Type updated! What else?*",
            parse_mode="Markdown",
            reply_markup=_edit_field_keyboard(),
        )

    # ── Edit Category — show category buttons ────────────────────────────────
    elif data == "edit_category":
        await query.edit_message_text(
            f"*Select a category ({row['type']}):*",
            parse_mode="Markdown",
            reply_markup=_category_keyboard(row["type"]),
        )

    elif data.startswith("set_cat_"):
        new_cat = data[len("set_cat_"):]
        row["category"] = new_cat
        context.user_data["pending_txn"] = row
        await query.edit_message_text(
            _format_card(row) + "\n\n*Category updated! What else?*",
            parse_mode="Markdown",
            reply_markup=_edit_field_keyboard(),
        )

    # ── Edit Amount — ask for text reply ─────────────────────────────────────
    elif data == "edit_amount":
        context.user_data["edit_field"] = "amount"
        await query.edit_message_text(
            _format_card(row) + "\n\n*Send the new amount:*",
            parse_mode="Markdown",
        )

    # ── Edit Note — ask for text reply ───────────────────────────────────────
    elif data == "edit_note":
        context.user_data["edit_field"] = "note"
        await query.edit_message_text(
            _format_card(row) + "\n\n*Send the new note:*",
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Text reply handler for amount / note edits
# ─────────────────────────────────────────────────────────────────────────────

async def handle_edit_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = str(update.effective_user.id)
    username = (
        update.effective_user.username
        or update.effective_user.first_name
        or "Unknown"
    )

    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 You need to log in first. Use /start to begin.")
        return

    edit_field = context.user_data.get("edit_field")
    row        = context.user_data.get("pending_txn")

    # If no edit is pending, treat as a new transaction
    if not edit_field or not row:
        await handle_message(update, context)
        return

    text = update.message.text.strip()
    context.user_data.pop("edit_field", None)

    if edit_field == "amount":
        try:
            row["amount"] = float(text.replace(",", "").replace("₹", "").strip())
        except ValueError:
            await update.message.reply_text(
                "⚠️ Invalid amount. Please send a number (e.g. 500)."
            )
            context.user_data["edit_field"] = "amount"
            return

    elif edit_field == "note":
        row["note"] = text[:100]

    context.user_data["pending_txn"] = row

    await update.message.reply_text(
        _format_card(row),
        parse_mode="Markdown",
        reply_markup=_confirm_keyboard(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────────────────────────────────────

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


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start and enter the password first.")
        return
    await update.message.reply_text("⏳ Calculating your balance...")
    try:
        data = get_balance(user_id)
        net_all       = data["net_balance"]
        net_month     = data["month_net"]
        net_all_icon  = "🟢" if net_all   >= 0 else "🔴"
        net_month_icon= "🟢" if net_month >= 0 else "🔴"

        msg = (
            f"💰 *Remaining Balance — {data['month']}*\n\n"
            f"📅 *This Month*\n"
            f"  Income  : ₹{data['month_income']:,.2f}\n"
            f"  Expense : ₹{data['month_expense']:,.2f}\n"
            f"  {net_month_icon} Net     : ₹{net_month:,.2f}\n\n"
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
        await update.message.reply_text("⚠️ Could not fetch balance. Try again later.")


async def fix_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start and enter the password first.")
        return
    await update.message.reply_text("🔄 Rebuilding summary sheet...")
    try:
        rebuild_summary()
        await update.message.reply_text("✅ Summary sheet rebuilt successfully!")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Failed to rebuild: {e}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 *Finance Bot — Help*\n\n"
        "*How to log a transaction:*\n"
        "Just type naturally! I understand English and Hindi.\n\n"
        "📊 *Commands:*\n"
        "/recent — Last 10 entries\n"
        "/summary — This month's summary\n"
        "/balance — Remaining balance details\n"
        "/fix — Rebuild summary sheet\n"
        "/logout — Log out of the bot\n"
        "/help — This help message",
        parse_mode="Markdown",
    )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Unknown command. Type /help for available options."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Register all handlers
# ─────────────────────────────────────────────────────────────────────────────

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        WAITING_PASSWORD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password)
        ],
    },
    fallbacks=[CommandHandler("start", start)],
)
ptb_app.add_handler(conv)
ptb_app.add_handler(CommandHandler("logout",  logout))
ptb_app.add_handler(CommandHandler("recent",  recent))
ptb_app.add_handler(CommandHandler("summary", summary))
ptb_app.add_handler(CommandHandler("balance", balance))
ptb_app.add_handler(CommandHandler("fix",     fix_summary))
ptb_app.add_handler(CommandHandler("help",    help_command))
ptb_app.add_handler(CallbackQueryHandler(handle_callback))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_reply))
ptb_app.add_handler(MessageHandler(filters.COMMAND, unknown))


# ─────────────────────────────────────────────────────────────────────────────
# Shared event loop for webhook mode
# ─────────────────────────────────────────────────────────────────────────────

_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)
_loop.run_until_complete(ptb_app.initialize())
logger.info("PTB application initialized and ready")


# ─────────────────────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────────────────────

flask_app = Flask(__name__)


@flask_app.get("/")
def health():
    return jsonify({"status": "ok", "service": "telegram-finance-bot"})


@flask_app.post("/webhook")
def webhook():
    data   = request.get_json(force=True)
    update = Update.de_json(data, ptb_app.bot)
    _loop.run_until_complete(ptb_app.process_update(update))
    return jsonify({"ok": True})


@flask_app.get("/set_webhook")
def set_webhook():
    webhook_url = os.getenv("WEBHOOK_URL", "").rstrip("/")
    if not webhook_url:
        return jsonify({"error": "WEBHOOK_URL env var not set"}), 400
    full_url = f"{webhook_url}/webhook"
    _loop.run_until_complete(ptb_app.bot.set_webhook(url=full_url))
    logger.info(f"Webhook registered: {full_url}")
    return jsonify({"ok": True, "webhook_url": full_url})


@flask_app.get("/delete_webhook")
def delete_webhook():
    _loop.run_until_complete(ptb_app.bot.delete_webhook())
    return jsonify({"ok": True, "message": "Webhook deleted"})


# ─────────────────────────────────────────────────────────────────────────────
# Entry point — python bot.py → polling mode (local dev)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    webhook_url = os.getenv("WEBHOOK_URL", "")
    if webhook_url:
        port = int(os.getenv("PORT", 8080))
        logger.info(f"🚀 Webhook mode — Flask on port {port}")
        flask_app.run(host="0.0.0.0", port=port)
    else:
        logger.info("🔄 Polling mode — local dev")
        _loop.run_until_complete(ptb_app.shutdown())
        ptb_app.run_polling(allowed_updates=Update.ALL_TYPES)
