import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
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
    get_all_goals, get_goal_by_name, get_active_goals, get_completed_goals,
    create_goal, add_to_goal, break_goal, find_similar_goals, clear_goal_cache,
)
from auth import verify_password, is_authenticated, set_authenticated
from utils import format_summary, format_recent
from goal_handler import format_goal_card, format_goal_complete, format_goals_list, format_goal_details

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
# Bot Command Menu Registration
# ─────────────────────────────────────────────────────────────────────────────

async def register_commands(app: Application) -> None:
    """
    Register all bot commands with Telegram.
    This makes them appear in the command menu when user types "/" or taps menu.
    """
    commands = [
        BotCommand("start", "Start bot & login"),
        BotCommand("recent", "Show last 10 transactions"),
        BotCommand("summary", "Monthly income/expense summary"),
        BotCommand("balance", "View net balance & goals breakdown"),
        BotCommand("goal", "Manage savings goals (set/add/view/break/list)"),
        BotCommand("logout", "Log out from bot"),
        BotCommand("help", "Show help & all available commands"),
    ]
    
    try:
        await app.bot.set_my_commands(commands)
        logger.info(f"✅ Registered {len(commands)} bot commands")
    except Exception as e:
        logger.error(f"Failed to register commands: {e}", exc_info=True)


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

    prompt_msg = await update.message.reply_text(
        f"🔐 Welcome,\n\n"
        "This bot is password-protected.\n"
        "Please enter the *password* to continue:",
        parse_mode="Markdown",
    )
    # Save the bot's prompt message ID so we can delete it later
    context.user_data["password_prompt_msg_id"] = prompt_msg.message_id
    return WAITING_PASSWORD


async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    entered = update.message.text.strip()

    if verify_password(entered):
        set_authenticated(user_id, True)
        # Delete the user's password message for security
        try:
            await update.message.delete()
        except Exception:
            pass  # deletion may fail if bot lacks permission — not critical
        # Delete the bot's "please enter password" prompt message
        prompt_msg_id = context.user_data.get("password_prompt_msg_id")
        if prompt_msg_id:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=prompt_msg_id,
                )
            except Exception:
                pass  # ignore if already deleted or no permission
        await update.message.reply_text(
            "🔓 *Access granted!* Welcome Ashish!.",
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
        active_goals = get_active_goals()
        if active_goals:
            goal_check = await detect_goal_deposit(text)
            if goal_check and goal_check.get("is_goal_deposit") and goal_check.get("amount"):
                amount = float(goal_check["amount"])
                goal_hint = goal_check.get("goal_hint", "").strip().lower() if goal_check.get("goal_hint") else None
                
                # Try to match goal hint to a goal name
                matched_goal = None
                if goal_hint:
                    for goal in active_goals:
                        if goal_hint in goal.get("Name", "").lower():
                            matched_goal = goal
                            break
                
                # If multiple goals and no match, show selection buttons
                if len(active_goals) > 1 and not matched_goal:
                    context.user_data["pending_goal_deposit"] = {
                        "amount": amount,
                    }
                    
                    keyboard = [
                        [InlineKeyboardButton(
                            f"💰 {goal['Name']} (₹{float(goal.get('Saved', 0)):,.0f}/₹{float(goal.get('Target', 0)):,.0f})",
                            callback_data=f"goal_deposit:{goal['Name']}"
                        )]
                        for goal in active_goals
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        f"💡 Which goal should I add ₹{amount:,.2f} to?",
                        reply_markup=reply_markup,
                    )
                    return
                
                # Single goal or matched goal
                target_goal = matched_goal or active_goals[0]
                goal_name = target_goal["Name"]
                
                # Check for overpayment
                saved_so_far = float(target_goal.get("Saved", 0))
                target_amt   = float(target_goal.get("Target", 0))
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
                
                goal, just_completed = add_to_goal(goal_name, amount, username)
                
                if just_completed:
                    await update.message.reply_text(
                        f"🎯 *Goal deposit saved!* ₹{amount:,.2f} logged.\n\n"
                        f"{format_goal_complete(goal)}",
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
        
        # Gather goal info
        active_goals = get_active_goals()
        completed_goals = get_completed_goals()
        
        total_locked = sum(float(g.get("Saved", 0)) for g in completed_goals)
        total_saved_active = sum(float(g.get("Saved", 0)) for g in active_goals)
        
        lines = [
            f"{icon} *Net Balance: ₹{net_all:,.2f}*",
            f"{'─' * 32}",
        ]
        
        # Active goals breakdown
        if active_goals:
            lines.append(f"\n✅ *Active Goals ({len(active_goals)}):*")
            for goal in active_goals:
                name = goal.get("Name", "")
                saved = float(goal.get("Saved", 0))
                target = float(goal.get("Target", 0))
                remaining = target - saved
                pct = (saved / target * 100) if target > 0 else 0
                lines.append(
                    f"   • {name}: ₹{saved:,.0f}/₹{target:,.0f} ({pct:.0f}%) — ₹{remaining:,.0f} to go"
                )
            lines.append(f"   💰 Total in Active: ₹{total_saved_active:,.2f}")
        
        # Completed goals (locked amount)
        if completed_goals:
            lines.append(f"\n✨ *Completed Goals ({len(completed_goals)}):*")
            for goal in completed_goals:
                name = goal.get("Name", "")
                saved = float(goal.get("Saved", 0))
                lines.append(f"   🔒 {name}: ₹{saved:,.2f} (locked)")
            lines.append(f"   🔐 Total Locked: ₹{total_locked:,.2f}")
        
        lines.append(f"\n{'─' * 32}")
        
        msg = "\n".join(lines)
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
        "/balance — Net balance + goals breakdown\n\n"
        "🎯 *Goal Tracker (Multiple Goals)*\n"
        "/goal — Show all goals\n"
        "/goal list — List all goals\n"
        "/goal set <name> \\| <amount> \\| <deadline> — Create goal\n"
        "/goal view <name> — View specific goal\n"
        "/goal add <name> <amount> — Add savings to goal\n"
        "/goal break <name> — Delete goal & refund balance\n\n"
        "🔐 *Account*\n"
        "/logout — Log out\n"
        "/help — This message",
        parse_mode="Markdown",
    )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Use /help.")


# ─────────────────────────────────────────────────────────────────────────────
# Goal command handlers — Multiple Goals Support
# ─────────────────────────────────────────────────────────────────────────────

async def _goal_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all goals (active and completed) with detailed breakdown."""
    try:
        active_goals = get_active_goals()
        completed_goals = get_completed_goals()
        
        msg = format_goals_list(active_goals, completed_goals)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"goal_status error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Could not fetch goals. Try again.")


async def _goal_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for _goal_status."""
    await _goal_status(update, context)


async def _goal_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /goal set <name> | <amount> | <deadline(optional)>
    Create a new goal (no replacement, add to list).
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
        # Check if goal with this name already exists
        existing = get_goal_by_name(name)
        if existing:
            await update.message.reply_text(
                f"⚠️ *Goal '{name}' already exists!*\n\n"
                f"Use a different name or use `/goal break {name}` to delete it first.",
                parse_mode="Markdown",
            )
            return

        goal = create_goal(name, target, deadline)
        await update.message.reply_text(
            f"✅ *Goal created!*\n\n{format_goal_card(goal)}",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"goal_set error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Could not create goal. Try again.")


async def _goal_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /goal add <name> <amount>
    Add money toward a specific goal.
    """
    if len(context.args) < 3:
        await update.message.reply_text(
            "⚠️ *Usage:* `/goal add <goal_name> <amount>`\n"
            "*Example:* `/goal add \"Goa Trip\" 2000`",
            parse_mode="Markdown",
        )
        return

    goal_name = context.args[1]
    try:
        amount = float(context.args[2].replace(",", "").replace("₹", "").strip())
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
        goal = get_goal_by_name(goal_name)
        if not goal:
            await update.message.reply_text(
                f"❌ Goal '{goal_name}' not found.\n\n"
                f"Use `/goal list` to see all goals.",
                parse_mode="Markdown",
            )
            return

        if goal.get("Status", "").strip().lower() != "active":
            await update.message.reply_text(
                f"❌ Goal '{goal_name}' is not active.\n\n"
                f"Use `/goal list` to view goal status.",
                parse_mode="Markdown",
            )
            return

        # Check for overpayment
        saved_so_far = float(goal.get("Saved", 0))
        target_amt   = float(goal.get("Target", 0))
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

        updated_goal, just_completed = add_to_goal(goal_name, amount, username)

        if updated_goal is None:
            await update.message.reply_text(
                f"❌ Could not update goal. Please try again.",
                parse_mode="Markdown",
            )
            return

        if just_completed:
            await update.message.reply_text(
                f"➕ *Deposit logged*\n\n"
                f"{format_goal_complete(updated_goal)}",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"➕ *₹{amount:,.2f} deposited & logged*\n\n"
                f"{format_goal_card(updated_goal)}",
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error(f"goal_add error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Could not update goal. Try again.")


async def _goal_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /goal view <name>
    Show detailed view of a specific goal.
    """
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ *Usage:* `/goal view <goal_name>`\n"
            "*Example:* `/goal view \"Goa Trip\"`",
            parse_mode="Markdown",
        )
        return

    goal_name = context.args[1]
    
    try:
        goal = get_goal_by_name(goal_name)
        if not goal:
            await update.message.reply_text(
                f"❌ Goal '{goal_name}' not found.\n\n"
                f"Use `/goal list` to see all goals.",
                parse_mode="Markdown",
            )
            return

        msg = format_goal_details(goal)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"goal_view error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Could not fetch goal. Try again.")


async def _goal_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks for goal selection and confirmation."""
    query = update.callback_query
    await query.answer()

    data = query.data
    
    # ── Goal deposit selection ────────────────────────────────────────────────
    if data.startswith("goal_deposit:"):
        goal_name = data.replace("goal_deposit:", "", 1)
        pending = context.user_data.pop("pending_goal_deposit", None)
        
        if not pending:
            await query.edit_message_text("⚠️ Session expired. Please try again.")
            return
        
        amount = pending.get("amount", 0)
        username = (
            query.from_user.username
            or query.from_user.first_name
            or "goal"
        )
        
        try:
            goal = get_goal_by_name(goal_name)
            if not goal:
                await query.edit_message_text(f"❌ Goal '{goal_name}' not found.")
                return
            
            # Check for overpayment
            saved_so_far = float(goal.get("Saved", 0))
            target_amt   = float(goal.get("Target", 0))
            remaining    = round(target_amt - saved_so_far, 2)
            
            if amount > remaining:
                await query.edit_message_text(
                    f"⚠️ *Deposit failed — amount exceeds limit!*\n"
                    f"Only ₹{remaining:,.2f} more needed.",
                    parse_mode="Markdown",
                )
                return
            
            updated_goal, just_completed = add_to_goal(goal_name, amount, username)
            
            if just_completed:
                await query.edit_message_text(
                    f"✅ ₹{amount:,.2f} added to *{goal_name}*\n\n"
                    f"{format_goal_complete(updated_goal)}",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text(
                    f"✅ ₹{amount:,.2f} added to *{goal_name}*\n\n"
                    f"{format_goal_card(updated_goal)}",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error(f"goal_deposit callback error: {e}", exc_info=True)
            await query.edit_message_text("⚠️ Something went wrong. Try again.")
    
    # ── Goal break confirmation ────────────────────────────────────────────────
    elif data.startswith("goal_break:"):
        # Decode goal name (handle escaped characters)
        parts = data.replace("goal_break:", "", 1).split("|")
        goal_name = parts[0].replace("\\:", ":").replace("\\|", "|")
        action = parts[1] if len(parts) > 1 else ""
        
        if action == "yes":
            username = (
                query.from_user.username
                or query.from_user.first_name
                or "goal"
            )
            
            try:
                goal = get_goal_by_name(goal_name)
                if not goal:
                    await query.edit_message_text(f"❌ Goal '{goal_name}' not found.")
                    return
                
                saved = float(goal.get("Saved", 0))
                status = goal.get("Status", "").strip().lower()
                
                # Break the goal (works for both active and completed)
                success = break_goal(goal_name, username)
                
                if not success:
                    await query.edit_message_text(
                        f"⚠️ Could not delete goal '{goal_name}'. Try again.",
                        parse_mode="Markdown",
                    )
                    return
                
                # Clear cache to force reload from Google Sheets
                clear_goal_cache()
                
                # Get updated stats
                active_goals = get_active_goals()
                completed_goals = get_completed_goals()
                balance_data = get_balance(str(query.from_user.id))
                net_balance = balance_data.get("net_balance", 0)
                
                # Build detailed summary
                lines = [
                    f"✅ *Goal Removed*",
                    f"{'━' * 32}",
                    f"🗑️  *{goal_name}* has been deleted.",
                ]
                
                if saved > 0:
                    lines.append(f"💰 *Refunded:* ₹{saved:,.2f}")
                
                lines.extend([
                    f"💳 *New Available Balance:* ₹{net_balance:,.2f}",
                    f"{'━' * 32}",
                ])
                
                # Show remaining goals summary
                if active_goals or completed_goals:
                    if active_goals:
                        total_active_saved = sum(float(g.get("Saved", 0)) for g in active_goals)
                        lines.append(f"✅ *Active Goals:* {len(active_goals)} (₹{total_active_saved:,.2f} saved)")
                    
                    if completed_goals:
                        total_completed = sum(float(g.get("Saved", 0)) for g in completed_goals)
                        lines.append(f"✨ *Locked Goals:* {len(completed_goals)} (₹{total_completed:,.2f} locked)")
                else:
                    lines.append("📌 No goals remaining.")
                
                lines.append(f"{'━' * 32}")
                
                await query.edit_message_text(
                    "\n".join(lines),
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"goal_break callback error: {e}", exc_info=True)
                await query.edit_message_text("⚠️ Could not delete goal. Try again.")
        else:
            await query.edit_message_text(
                f"❌ *Cancelled.* Goal *{goal_name}* is safe.",
                parse_mode="Markdown",
            )


def _find_similar_goals(goal_name: str, max_suggestions: int = 3) -> list[dict]:
    """
    Find goals with names similar to the given name (case-insensitive substring match).
    Returns list of matching goals sorted by name similarity.
    """
    from difflib import SequenceMatcher
    
    goal_name_lower = goal_name.strip().lower()
    all_goals = get_all_goals()
    
    # Filter goals that contain the search term or vice versa
    matching = []
    for goal in all_goals:
        name_lower = goal.get("Name", "").strip().lower()
        status = goal.get("Status", "").strip().lower()
        
        # Only suggest active and completed goals (not deleted)
        if status == "deleted":
            continue
            
        # Check if goal name contains search term or vice versa
        if goal_name_lower in name_lower or name_lower in goal_name_lower:
            matching.append((goal, SequenceMatcher(None, goal_name_lower, name_lower).ratio()))
    
    # Sort by similarity (highest first)
    matching.sort(key=lambda x: x[1], reverse=True)
    
    return [goal for goal, _ in matching[:max_suggestions]]


async def _goal_break(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /goal break <name>
    Parse entire text after "/goal break" as goal name (preserving spaces).
    Ask confirmation before breaking a goal (active or completed).
    """
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ *Usage:* `/goal break <goal_name>`\n"
            "*Example:* `/goal break Car Loan`",
            parse_mode="Markdown",
        )
        return

    # Parse entire text after "/goal break" to preserve spaces
    goal_name = " ".join(context.args[1:]).strip()
    
    if not goal_name:
        await update.message.reply_text(
            "⚠️ Please provide a goal name.\n"
            "*Example:* `/goal break Car Loan`",
            parse_mode="Markdown",
        )
        return
    
    try:
        # Try exact match (case-insensitive)
        goal = get_goal_by_name(goal_name)
        
        if goal:
            status = goal.get("Status", "").strip().lower()
            
            # Allow breaking both active and completed goals
            saved = float(goal.get("Saved", 0))
            
            # Escape special characters in goal name for callback data
            encoded_goal_name = goal_name.replace(":", "\\:").replace("|", "\\|")

            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, break it", callback_data=f"goal_break:{encoded_goal_name}|yes"),
                    InlineKeyboardButton("❌ No, keep it",    callback_data=f"goal_break:{encoded_goal_name}|no"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            refund_note = (
                f"\n\n💰 ₹{saved:,.2f} will be *returned* to your available balance."
                if saved > 0 else ""
            )
            
            status_note = " (locked)" if status == "completed" else ""

            await update.message.reply_text(
                f"🗑️ *Break goal \"{goal_name}\"{status_note}?*{refund_note}\n\n"
                f"This cannot be undone.",
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
        else:
            # No exact match - suggest similar goals
            similar = _find_similar_goals(goal_name)
            
            if similar:
                suggestions = "\n".join([f"• {g.get('Name')}" for g in similar])
                await update.message.reply_text(
                    f"❌ Goal '{goal_name}' not found.\n\n"
                    f"Did you mean?\n{suggestions}\n\n"
                    f"Use `/goal list` to see all goals.",
                    parse_mode="Markdown",
                )
            else:
                all_goals = get_all_goals()
                active_count = len([g for g in all_goals if g.get("Status", "").strip().lower() == "active"])
                completed_count = len([g for g in all_goals if g.get("Status", "").strip().lower() == "completed"])
                
                await update.message.reply_text(
                    f"❌ Goal '{goal_name}' not found.\n\n"
                    f"📊 Available goals: {active_count} active, {completed_count} completed\n"
                    f"Use `/goal list` to see all goals.",
                    parse_mode="Markdown",
                )
    except Exception as e:
        logger.error(f"goal_break error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Could not break goal. Try again.")


async def goal_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Route /goal subcommands:
      /goal              → show list of all goals
      /goal list         → alias for show
      /goal set ...      → create new goal
      /goal view <name>  → view specific goal
      /goal add <name> <amt> → add savings to goal
      /goal break <name> → delete/break goal
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
    elif sub == "view":
        await _goal_view(update, context)
    elif sub == "break":
        await _goal_break(update, context)
    elif sub == "list":
        await _goal_list(update, context)
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

# Register bot commands with Telegram
_loop.run_until_complete(register_commands(ptb_app))
logger.info("Bot command menu registered.")

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
