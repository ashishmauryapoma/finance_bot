"""
Telegram Finance Management Bot
- Local dev:  python bot.py  → polling mode
- Render.com: gunicorn bot:flask_app --worker-class sync --workers 1
              Set WEBHOOK_URL env var to activate webhook mode
"""

import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    PicklePersistence,
)
from dotenv import load_dotenv

from groq_handler import extract_transaction, EXPENSE_CATEGORIES, INCOME_CATEGORIES
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

# ─────────────────────────────────────────────────────────────────────────────
# Conversation states
# ─────────────────────────────────────────────────────────────────────────────

WAITING_PASSWORD = 1
_IST = timezone(timedelta(hours=5, minutes=30))

# ─────────────────────────────────────────────────────────────────────────────
# PTB Application — built once, reused across requests
# ─────────────────────────────────────────────────────────────────────────────

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set.")


def _make_app() -> Application:
    persistence = PicklePersistence(filepath="bot_persistence.pkl")
    return (
        Application.builder()
        .token(TOKEN)
        .persistence(persistence)
        .build()
    )


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
    type_label = "💸 Expense" if row["type"] == "expense" else "💰 Income"
    return (
        f"📤 *Transaction Preview*\n"
        f"{'─' * 28}\n"
        f"📅 *Date:*      {row['date']}\n"
        f"💱 *Type:*      {type_label}\n"
        f"📂 *Category:* {row['category']}\n"
        f"💵 *Amount:*   ₹{row['amount']:,.2f}\n"
        f"📝 *Note:*      {row['note']}\n"
        f"{'─' * 28}"
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Submit", callback_data="txn_submit"),
        InlineKeyboardButton("✏️ Edit",   callback_data="txn_edit"),
    ]])


def _edit_field_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💱 Type",     callback_data="edit_type"),
         InlineKeyboardButton("📂 Category", callback_data="edit_category")],
        [InlineKeyboardButton("💵 Amount",   callback_data="edit_amount"),
         InlineKeyboardButton("📝 Note",     callback_data="edit_note")],
        [InlineKeyboardButton("🔙 Back",     callback_data="edit_back")],
    ])


def _type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💸 Expense", callback_data="set_type_expense"),
        InlineKeyboardButton("💰 Income",  callback_data="set_type_income"),
    ]])


def _category_keyboard(txn_type: str) -> InlineKeyboardMarkup:
    cats = EXPENSE_CATEGORIES if txn_type == "expense" else INCOME_CATEGORIES
    rows = []
    for i in range(0, len(cats), 2):
        pair = cats[i:i+2]
        rows.append([
            InlineKeyboardButton(c, callback_data=f"set_cat_{c}")
            for c in pair
        ])
    return InlineKeyboardMarkup(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Auth handlers
# ─────────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    name    = update.effective_user.first_name or "there"

    if is_authenticated(user_id):
        await update.message.reply_text(
            f"👋 Welcome back, *{name}*!\n\n"
            "Just tell me what you spent or earned.\n\n"
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
            "Send me any transaction in plain language — English or Hindi!",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "❌ *Wrong password.* Please try again:",
        parse_mode="Markdown",
    )
    return WAITING_PASSWORD


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    set_authenticated(user_id, False)
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Logged out. Use /start to log in again."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main message handler
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

    # ── Edit reply (amount / note) ────────────────────────────────────────────
    edit_field = context.user_data.get("edit_field")
    row        = context.user_data.get("pending_txn")

    if edit_field and row:
        context.user_data.pop("edit_field", None)

        if edit_field == "amount":
            try:
                row["amount"] = float(text.replace(",", "").replace("₹", "").strip())
            except ValueError:
                await update.message.reply_text("⚠️ Invalid amount. Send a number like 500.")
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
        return

    # ── New transaction ───────────────────────────────────────────────────────
    await update.message.reply_chat_action("typing")
    try:
        transaction = await extract_transaction(text)
        if not transaction:
            await update.message.reply_text(
                "🤔 Couldn't understand that as a transaction. Please try again."
            )
            return

        row = _build_row(transaction, username)
        context.user_data["pending_txn"] = row
        context.user_data["username"]    = username

        await update.message.reply_text(
            _format_card(row),
            parse_mode="Markdown",
            reply_markup=_confirm_keyboard(),
        )
    except Exception as e:
        logger.error(f"handle_message error: {e}")
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")


# ─────────────────────────────────────────────────────────────────────────────
# Callback query handler
# ─────────────────────────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = str(query.from_user.id)
    data    = query.data

    # Answer immediately to remove Telegram's loading spinner
    await query.answer()

    if not is_authenticated(user_id):
        await query.edit_message_text("🔐 Session expired. Please /start again.")
        return

    row = context.user_data.get("pending_txn")

    if row is None:
        await query.edit_message_text(
            "⚠️ No pending transaction found.\nPlease send your transaction again."
        )
        return

    if data == "txn_submit":
        try:
            append_transaction(row)
            type_label = "💸 Expense" if row["type"] == "expense" else "💰 Income"
            await query.edit_message_text(
                f"✅ *Transaction Saved!*\n"
                f"{'─' * 28}\n"
                f"📅 *Date:*      {row['date']}\n"
                f"💱 *Type:*      {type_label}\n"
                f"📂 *Category:* {row['category']}\n"
                f"💵 *Amount:*   ₹{row['amount']:,.2f}\n"
                f"📝 *Note:*      {row['note']}\n"
                f"{'─' * 28}\n\n"
                f"📊 Recorded in Google Sheets!",
                parse_mode="Markdown",
            )
            context.user_data.pop("pending_txn", None)
        except Exception as e:
            logger.error(f"Submit error: {e}")
            await query.edit_message_text("⚠️ Failed to save. Please try again.")

    elif data == "txn_edit":
        await query.edit_message_text(
            _format_card(row) + "\n\n*What would you like to edit?*",
            parse_mode="Markdown",
            reply_markup=_edit_field_keyboard(),
        )

    elif data == "edit_back":
        await query.edit_message_text(
            _format_card(row),
            parse_mode="Markdown",
            reply_markup=_confirm_keyboard(),
        )

    elif data == "edit_type":
        await query.edit_message_text(
            _format_card(row) + "\n\n*Select transaction type:*",
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

    elif data == "edit_category":
        await query.edit_message_text(
            f"*Select a category ({row['type']}):*",
            parse_mode="Markdown",
            reply_markup=_category_keyboard(row["type"]),
        )

    elif data.startswith("set_cat_"):
        row["category"] = data[len("set_cat_"):]
        context.user_data["pending_txn"] = row
        await query.edit_message_text(
            _format_card(row) + "\n\n*Category updated! What else?*",
            parse_mode="Markdown",
            reply_markup=_edit_field_keyboard(),
        )

    elif data == "edit_amount":
        context.user_data["edit_field"] = "amount"
        await query.edit_message_text(
            _format_card(row) + "\n\n✏️ *Send the new amount:*",
            parse_mode="Markdown",
        )

    elif data == "edit_note":
        context.user_data["edit_field"] = "note"
        await query.edit_message_text(
            _format_card(row) + "\n\n✏️ *Send the new note:*",
            parse_mode="Markdown",
        )


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
        "Just type any transaction naturally.\n\n"
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
# Register handlers + build app
# ─────────────────────────────────────────────────────────────────────────────

def _register_handlers(app: Application):
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
    app.add_handler(conv)
    app.add_handler(CommandHandler("logout",  logout))
    app.add_handler(CommandHandler("recent",  recent))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("fix",     fix_summary))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))


# ─────────────────────────────────────────────────────────────────────────────
# Flask app — one fresh event loop per request (no shared loop issues)
# ─────────────────────────────────────────────────────────────────────────────

flask_app = Flask(__name__)

# Build and initialise the PTB app once at import time
_ptb_app = _make_app()
_register_handlers(_ptb_app)

# Use ONE persistent event loop (but never share it across threads)
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)
_loop.run_until_complete(_ptb_app.initialize())
logger.info("PTB app initialised.")


@flask_app.get("/")
def health():
    return jsonify({"status": "ok"})


@flask_app.post("/webhook")
def webhook():
    try:
        payload = request.get_json(force=True)
        update  = Update.de_json(payload, _ptb_app.bot)
        # process_update is the correct entry point — handles persistence flush too
        _loop.run_until_complete(_ptb_app.process_update(update))
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
    return jsonify({"ok": True})


@flask_app.get("/set_webhook")
def set_webhook():
    url = os.getenv("WEBHOOK_URL", "").rstrip("/")
    if not url:
        return jsonify({"error": "WEBHOOK_URL not set"}), 400
    full = f"{url}/webhook"
    _loop.run_until_complete(_ptb_app.bot.set_webhook(url=full))
    return jsonify({"ok": True, "webhook_url": full})


@flask_app.get("/delete_webhook")
def delete_webhook():
    _loop.run_until_complete(_ptb_app.bot.delete_webhook())
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
        _loop.run_until_complete(_ptb_app.shutdown())
        _ptb_app.run_polling(allowed_updates=Update.ALL_TYPES)
