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
from goals_handler import (
    cmd_new_goal, cmd_deposit, cmd_goals,
    cmd_goal_detail, cmd_delete_goal, cmd_all_goals,
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
            "/goals — Your savings goals\n"
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
# Transaction command handlers
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
        data    = get_balance(user_id)
        net_all = data["net_balance"]
        icon    = "🟢" if net_all >= 0 else "🔴"
        msg     = f"{icon} *Net Balance: ₹{net_all:,.2f}*"
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


# ─────────────────────────────────────────────────────────────────────────────
# Goals command handlers
# ─────────────────────────────────────────────────────────────────────────────

async def goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all active goals: /goals"""
    user_id  = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name or "Unknown"
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return
    try:
        msg = cmd_goals(username)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Goals error: {e}")
        await update.message.reply_text("⚠️ Could not fetch goals.")


async def all_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all goals including completed/cancelled: /allgoals"""
    user_id  = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name or "Unknown"
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return
    try:
        msg = cmd_all_goals(username)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"All goals error: {e}")
        await update.message.reply_text("⚠️ Could not fetch goals.")


async def new_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Create a new savings goal.
    Usage: /newgoal <Name> | <Target> | <DD-MM-YYYY>
    Example: /newgoal Trip to Goa | 50000 | 01-12-2026
    """
    user_id  = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name or "Unknown"
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return

    usage = (
        "📌 *Usage:* `/newgoal Name | Target | DD-MM-YYYY`\n\n"
        "Example:\n`/newgoal Trip to Goa | 50000 | 01-12-2026`"
    )

    if not context.args:
        await update.message.reply_text(usage, parse_mode="Markdown")
        return

    raw = " ".join(context.args)
    parts = [p.strip() for p in raw.split("|")]

    if len(parts) != 3:
        await update.message.reply_text(
            "❌ Wrong format. Use `|` to separate fields.\n\n" + usage,
            parse_mode="Markdown",
        )
        return

    name_str, target_str, deadline_str = parts

    try:
        target = float(target_str.replace(",", "").replace("₹", "").strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid target amount.", parse_mode="Markdown")
        return

    try:
        datetime.strptime(deadline_str, "%d-%m-%Y")
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid date format. Use DD-MM-YYYY (e.g. 01-12-2026)",
            parse_mode="Markdown",
        )
        return

    try:
        msg = cmd_new_goal(name_str, target, deadline_str, username)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"New goal error: {e}")
        await update.message.reply_text(f"⚠️ Failed to create goal: {e}")


async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Add money to a goal.
    Usage: /deposit <GoalID> <Amount>
    Example: /deposit A1B2C3D4 5000
    """
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return

    usage = "📌 *Usage:* `/deposit <GoalID> <Amount>`\n\nExample: `/deposit A1B2C3D4 5000`"

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(usage, parse_mode="Markdown")
        return

    goal_id    = context.args[0].strip().upper()
    amount_str = context.args[1].strip().replace(",", "").replace("₹", "")

    try:
        amount = float(amount_str)
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.", parse_mode="Markdown")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Amount must be positive.")
        return

    try:
        msg = cmd_deposit(goal_id, amount)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error(f"Deposit error: {e}")
        await update.message.reply_text("⚠️ Failed to deposit. Try again.")


async def goal_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Show full card for a single goal.
    Usage: /goal <GoalID>
    """
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return

    if not context.args:
        await update.message.reply_text(
            "📌 *Usage:* `/goal <GoalID>`", parse_mode="Markdown"
        )
        return

    goal_id = context.args[0].strip().upper()
    try:
        msg = cmd_goal_detail(goal_id)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Goal detail error: {e}")
        await update.message.reply_text("⚠️ Failed to fetch goal.")


async def cancel_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Cancel (soft-delete) a goal.
    Usage: /cancelgoal <GoalID>
    """
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return

    if not context.args:
        await update.message.reply_text(
            "📌 *Usage:* `/cancelgoal <GoalID>`", parse_mode="Markdown"
        )
        return

    goal_id = context.args[0].strip().upper()
    try:
        msg = cmd_delete_goal(goal_id)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Cancel goal error: {e}")
        await update.message.reply_text("⚠️ Failed to cancel goal.")


# ─────────────────────────────────────────────────────────────────────────────
# Help & unknown
# ─────────────────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 *Finance Bot — Help*\n\n"
        "Just type any transaction naturally and it gets saved instantly.\n\n"
        "📊 *Transactions*\n"
        "/recent — Last 10 entries\n"
        "/summary — Monthly summary\n"
        "/balance — Balance details\n"
        "/fix — Rebuild summary sheet\n\n"
        "🎯 *Savings Goals*\n"
        "/goals — View active goals\n"
        "/allgoals — All goals (incl. completed)\n"
        "/newgoal Name | Target | DD-MM-YYYY — Create goal\n"
        "/goal <ID> — Goal details\n"
        "/deposit <ID> <Amount> — Add savings\n"
        "/cancelgoal <ID> — Cancel a goal\n\n"
        "⚙️ *Account*\n"
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

# Transactions
ptb_app.add_handler(CommandHandler("logout",   logout))
ptb_app.add_handler(CommandHandler("recent",   recent))
ptb_app.add_handler(CommandHandler("summary",  summary))
ptb_app.add_handler(CommandHandler("balance",  balance))
ptb_app.add_handler(CommandHandler("fix",      fix_summary))

# Goals
ptb_app.add_handler(CommandHandler("goals",      goals))
ptb_app.add_handler(CommandHandler("allgoals",   all_goals))
ptb_app.add_handler(CommandHandler("newgoal",    new_goal))
ptb_app.add_handler(CommandHandler("goal",       goal_detail))
ptb_app.add_handler(CommandHandler("deposit",    deposit))
ptb_app.add_handler(CommandHandler("cancelgoal", cancel_goal))

# Catch-all
ptb_app.add_handler(CommandHandler("help",     help_command))
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
