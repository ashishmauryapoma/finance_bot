import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from dotenv import load_dotenv

from groq_handler import extract_transaction, detect_goal_deposit
from sheets_handler import (
    append_transaction, get_recent_transactions,
    get_summary, get_balance,
    get_goal, create_goal, add_to_goal, delete_goal,
)
from auth import verify_password, is_authenticated, set_authenticated
from utils import format_summary, format_recent
from goal_handler import format_goal_card, format_goal_complete

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
            f"👋 Welcome back, Ashish!\n\n"
            "Just tell me what you spent or earned and I'll save it.\n\n"
            "🔧 *Commands:*\n"
            "/recent — Last 10 transactions\n"
            "/summary — Monthly summary\n"
            "/balance — Balance details\n"
            "/goal — Savings goal tracker\n"
            "/logout — Log out\n"
            "/help — Help",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"🔐 Welcome,\n\n"
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
        # Delete the message containing the password for security
        try:
            await update.message.delete()
        except Exception:
            pass  # deletion may fail if bot lacks permission — not critical
        await update.message.reply_text(
            "🔓 *Access granted!* Welcome Ashish.",
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
        # ── Step 1: Check if message is a goal deposit ────────────────────────
        active_goal = get_goal()
        if active_goal:
            goal_check = await detect_goal_deposit(text)
            if goal_check and goal_check.get("is_goal_deposit") and goal_check.get("amount"):
                amount = float(goal_check["amount"])

                # ── Check for overpayment ──────────────────────────────────
                saved_so_far = float(active_goal.get("Saved", 0))
                target_amt   = float(active_goal.get("Target", 0))
                remaining    = round(target_amt - saved_so_far, 2)
                if amount > remaining:
                    await update.message.reply_text(
                        f"⚠️ *Deposit failed — amount exceeds goal limit!*\n\n"
                        f"💰 Already saved: ₹{saved_so_far:,.2f}\n"
                        f"🎯 Target: ₹{target_amt:,.2f}\n"
                        f"📌 *Only ₹{remaining:,.2f} more needed* to complete this goal.\n\n"
                        f"Please deposit ₹{remaining:,.2f} or less.",
                        parse_mode="Markdown",
                    )
                    return

                goal, just_completed = add_to_goal(amount, username)

                if just_completed:
                    saved  = float(goal.get("Saved", 0))
                    await update.message.reply_text(
                        f"🎯 *Goal deposit saved!* ₹{amount:,.2f} logged.\n\n"
                        f"{format_goal_complete(goal)}\n\n"
                        f"💡 ₹{saved:,.2f} auto-added to your income as *Goal Achieved*.",
                        parse_mode="Markdown",
                    )
                else:
                    await update.message.reply_text(
                        f"🎯 *Goal deposit saved!* ₹{amount:,.2f} logged.\n\n"
                        f"{format_goal_card(goal)}",
                        parse_mode="Markdown",
                    )
                return  # done — don't process as a normal transaction

        # ── Step 2: Normal transaction parsing ────────────────────────────────
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
# Finance command handlers
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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 *Finance Bot — Help*\n\n"
        "Just type any transaction naturally and it gets saved instantly.\n\n"
        "📋 *Transactions*\n"
        "/recent — Last 10 entries\n"
        "/summary — Monthly summary\n"
        "/balance — Net balance\n\n"
        "🎯 *Goal Tracker*\n"
        "/goal — View current goal\n"
        "/goal set <name> \\| <amount> \\| <deadline> — Create goal\n"
        "/goal add <amount> — Add savings to goal\n"
        "/goal delete — Remove current goal\n\n"
        "🔐 *Account*\n"
        "/logout — Log out\n"
        "/help — This message",
        parse_mode="Markdown",
    )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Use /help.")


# ─────────────────────────────────────────────────────────────────────────────
# Goal command handlers
# ─────────────────────────────────────────────────────────────────────────────

async def _goal_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the current goal progress card."""
    try:
        goal = get_goal()
        if not goal:
            await update.message.reply_text(
                "🎯 *No active goal.*\n\n"
                "Create one with:\n"
                "`/goal set <name> | <amount> | <deadline>`",
                parse_mode="Markdown",
            )
            return
        await update.message.reply_text(format_goal_card(goal), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"goal_status error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Could not fetch goal. Try again.")


async def _goal_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /goal set <name> | <amount> | <deadline(optional)>
    If a goal already exists, shows inline Yes/No buttons for confirmation.
    """
    raw   = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    parts = [p.strip() for p in raw.split("|")]

    if len(parts) < 2 or not parts[0]:
        await update.message.reply_text(
            "⚠️ *Usage:* `/goal set <name> | <amount> | <deadline>`\n\n"
            "*Example:*\n"
            "`/goal set Goa Trip | 50000 | 2026-12-01`\n"
            "_(deadline is optional)_",
            parse_mode="Markdown",
        )
        return

    name     = parts[0]
    deadline = parts[2].strip() if len(parts) >= 3 else ""

    try:
        target = float(parts[1].replace(",", "").replace("₹", "").strip())
    except ValueError:
        await update.message.reply_text(
            "⚠️ Invalid amount. Use a plain number like `50000`.",
            parse_mode="Markdown",
        )
        return

    if target <= 0:
        await update.message.reply_text("⚠️ Target amount must be greater than zero.")
        return

    try:
        existing = get_goal()
        if existing:
            # Store the new goal details and show inline buttons
            context.user_data["pending_goal"] = {
                "name": name, "target": target, "deadline": deadline
            }
            saved = float(existing.get("Saved", 0))
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes", callback_data="goal_replace:yes"),
                    InlineKeyboardButton("❌ No", callback_data="goal_replace:no"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"⚠️ *You already have an active goal:*\n\n"
                f"🎯 *{existing['Name']}* — ₹{float(existing['Target']):,.0f} target\n"
                f"💰 Saved so far: ₹{saved:,.2f}\n\n"
                f"Replacing it will *refund ₹{saved:,.2f}* back to your net balance "
                f"and start fresh with *{name}*.\n\n"
                f"Confirm replacement?",
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
            return

        # No existing goal — create immediately
        goal = create_goal(name, target, deadline)
        await update.message.reply_text(
            f"✅ *Goal created!*\n\n{format_goal_card(goal)}",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"goal_set error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Could not create goal. Try again.")


async def _goal_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all inline button callbacks for goal confirmations."""
    query = update.callback_query
    await query.answer()  # removes the loading spinner on the button

    data   = query.data            # e.g. "goal_replace:yes" or "goal_delete:no"
    action, choice = data.split(":")

    username = (
        query.from_user.username
        or query.from_user.first_name
        or "goal"
    )

    # ── Goal replacement ──────────────────────────────────────────────────────
    if action == "goal_replace":
        if choice == "yes":
            pending = context.user_data.pop("pending_goal", None)
            if not pending:
                await query.edit_message_text(
                    "⚠️ Session expired. Please run `/goal set` again."
                )
                return
            try:
                delete_goal(username)
                goal = create_goal(pending["name"], pending["target"], pending["deadline"])
                await query.edit_message_text(
                    f"✅ *Old goal removed & balance refunded.*\n\n"
                    f"🎯 *New goal created!*\n\n{format_goal_card(goal)}",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"goal_replace callback error: {e}", exc_info=True)
                await query.edit_message_text("⚠️ Something went wrong. Try again.")
        else:
            context.user_data.pop("pending_goal", None)
            await query.edit_message_text(
                "❌ *Cancelled.* Your current goal is still active.",
                parse_mode="Markdown",
            )

    # ── Goal deletion ─────────────────────────────────────────────────────────
    elif action == "goal_delete":
        if choice == "yes":
            try:
                goal = get_goal()
                if not goal:
                    await query.edit_message_text("🎯 No active goal to delete.")
                    return
                name  = goal["Name"]
                saved = float(goal.get("Saved", 0))
                delete_goal(username)
                if saved > 0:
                    await query.edit_message_text(
                        f"🗑️ Goal *{name}* deleted.\n\n"
                        f"💰 ₹{saved:,.2f} you had deposited has been refunded to your balance.",
                        parse_mode="Markdown",
                    )
                else:
                    await query.edit_message_text(
                        f"🗑️ Goal *{name}* deleted.",
                        parse_mode="Markdown",
                    )
            except Exception as e:
                logger.error(f"goal_delete callback error: {e}", exc_info=True)
                await query.edit_message_text("⚠️ Could not delete goal. Try again.")
        else:
            await query.edit_message_text(
                "❌ *Cancelled.* Your goal is safe.",
                parse_mode="Markdown",
            )


async def _goal_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /goal add <amount>
    Add money toward the active goal.
    Logs the deposit as a transaction and auto-books income on completion.
    """
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ *Usage:* `/goal add <amount>`\n"
            "*Example:* `/goal add 2000`",
            parse_mode="Markdown",
        )
        return

    try:
        amount = float(context.args[1].replace(",", "").replace("₹", "").strip())
    except ValueError:
        await update.message.reply_text(
            "⚠️ Invalid amount. Use a plain number like `2000`.",
            parse_mode="Markdown",
        )
        return

    if amount <= 0:
        await update.message.reply_text("⚠️ Amount must be greater than zero.")
        return

    username = (
        update.effective_user.username
        or update.effective_user.first_name
        or "goal"
    )

    try:
        # ── Check for overpayment before depositing ───────────────────────────
        current_goal = get_goal()
        if current_goal:
            saved_so_far = float(current_goal.get("Saved", 0))
            target_amt   = float(current_goal.get("Target", 0))
            remaining    = round(target_amt - saved_so_far, 2)
            if amount > remaining:
                await update.message.reply_text(
                    f"⚠️ *Deposit failed — amount exceeds goal limit!*\n\n"
                    f"💰 Already saved: ₹{saved_so_far:,.2f}\n"
                    f"🎯 Target: ₹{target_amt:,.2f}\n"
                    f"📌 *Only ₹{remaining:,.2f} more needed* to complete this goal.\n\n"
                    f"Please deposit ₹{remaining:,.2f} or less.",
                    parse_mode="Markdown",
                )
                return

        goal, just_completed = add_to_goal(amount, username)

        if goal is None:
            await update.message.reply_text(
                "🎯 No active goal or goal is already completed.\n"
                "Create a new one with `/goal set`.",
                parse_mode="Markdown",
            )
            return

        saved  = float(goal.get("Saved", 0))
        target = float(goal.get("Target", 0))

        if just_completed:
            await update.message.reply_text(
                f"➕ *Deposit logged*\n\n"
                f"{format_goal_complete(goal)}\n\n"
                f"💡 ₹{saved:,.2f} auto-added to your income as *Goal Achieved*.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"➕ *₹{amount:,.2f} deposited & logged*\n\n"
                f"{format_goal_card(goal)}",
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error(f"goal_add error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Could not update goal. Try again.")


async def _goal_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/goal delete — ask confirmation via inline buttons before deleting."""
    try:
        goal = get_goal()
        if not goal:
            await update.message.reply_text("🎯 No active goal to delete.")
            return

        name  = goal["Name"]
        saved = float(goal.get("Saved", 0))

        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, delete it", callback_data="goal_delete:yes"),
                InlineKeyboardButton("❌ No, keep it",    callback_data="goal_delete:no"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        refund_note = (
            f"\n\n💰 ₹{saved:,.2f} will be *refunded* to your balance."
            if saved > 0 else ""
        )

        await update.message.reply_text(
            f"🗑️ *Delete goal \"{name}\"?*{refund_note}\n\n"
            f"This cannot be undone.",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error(f"goal_delete error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Could not delete goal. Try again.")


async def goal_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Route /goal subcommands:
      /goal            → show status
      /goal set ...    → create goal
      /goal add <amt>  → add savings
      /goal delete     → remove goal
    """
    user_id = str(update.effective_user.id)
    if not is_authenticated(user_id):
        await update.message.reply_text("🔐 Please /start first.")
        return

    sub = context.args[0].lower() if context.args else ""

    if sub == "set":
        await _goal_set(update, context)
    elif sub == "add":
        await _goal_add(update, context)
    elif sub == "delete":
        await _goal_delete(update, context)
    else:
        await _goal_status(update, context)


# ─────────────────────────────────────────────────────────────────────────────
# Register handlers
# ─────────────────────────────────────────────────────────────────────────────

conv = ConversationHandler(
    entry_points=[
        CommandHandler("start", start),
    ],
    states={
        WAITING_PASSWORD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password)
        ],
    },
    fallbacks=[
        CommandHandler("start", start),
    ],
    per_message=False,
)

ptb_app.add_handler(conv)
ptb_app.add_handler(CallbackQueryHandler(_goal_button_callback, pattern="^goal_"))
ptb_app.add_handler(CommandHandler("logout",  logout))
ptb_app.add_handler(CommandHandler("recent",  recent))
ptb_app.add_handler(CommandHandler("summary", summary))
ptb_app.add_handler(CommandHandler("balance", balance))
ptb_app.add_handler(CommandHandler("help",    help_command))
ptb_app.add_handler(CommandHandler("goal",    goal_router))
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
    _loop.run_until_complete(ptb_app.bot.set_webhook(
        url=full,
        allowed_updates=["message", "callback_query", "inline_query"],
    ))
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
