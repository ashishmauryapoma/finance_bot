"""
goals_handler.py — Business logic + message formatting for savings goals
"""

from datetime import datetime, timezone, timedelta
import math

from goals_sheets import (
    create_goal, deposit_to_goal, get_goals,
    delete_goal, get_goal_by_id,
)

_IST = timezone(timedelta(hours=5, minutes=30))


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_deadline(deadline_str: str) -> datetime:
    """Parse DD-MM-YYYY → datetime (IST-aware)."""
    return datetime.strptime(deadline_str, "%d-%m-%Y").replace(
        tzinfo=_IST
    )


def _days_left(deadline_str: str) -> int:
    now      = datetime.now(tz=_IST).replace(hour=0, minute=0, second=0, microsecond=0)
    deadline = _parse_deadline(deadline_str).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(0, (deadline - now).days)


def _progress_bar(pct: float, width: int = 14) -> str:
    filled = math.floor(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def format_goal_card(goal: dict) -> str:
    """Render the fancy goal card shown in the example."""
    name       = goal["Name"]
    target     = float(goal["Target"])
    saved      = float(goal["Saved"])
    deadline   = goal["Deadline"]
    status     = goal["Status"]
    goal_id    = goal["ID"]

    pct        = min(100.0, (saved / target * 100)) if target else 0
    bar        = _progress_bar(pct)
    days       = _days_left(deadline)
    remaining  = max(0.0, target - saved)

    # Daily rate needed
    if days > 0 and remaining > 0:
        daily_needed = remaining / days
    else:
        daily_needed = 0

    # On-track heuristic: days elapsed suggests how much should be saved by now
    try:
        created_dt = datetime.strptime(goal.get("Created", "01-01-2000"), "%d-%m-%Y").replace(tzinfo=_IST)
        total_days = (_parse_deadline(deadline) - created_dt).days or 1
        elapsed    = total_days - days
        expected   = target * elapsed / total_days
        on_track   = saved >= expected * 0.9   # within 10% is fine
    except Exception:
        on_track = daily_needed == 0

    if status == "completed":
        status_line = "🎉 *GOAL REACHED!* Congratulations!"
    elif status == "cancelled":
        status_line = "🚫 *Cancelled*"
    elif days == 0:
        status_line = "⏰ *Deadline today!*"
    elif on_track:
        status_line = f"✅ On track! Keep saving ₹{daily_needed:,.0f}/day"
    else:
        shortfall   = daily_needed - (saved / max(elapsed, 1)) if elapsed > 0 else daily_needed
        status_line = f"⚡ Off track — save ₹{daily_needed:,.0f}/day to catch up"

    lines = [
        f"🎯 *{name}* `[{goal_id}]`",
        "━" * 22,
        f"💰 Saved:    ₹{saved:,.2f} / ₹{target:,.2f}",
        f"📊 Progress: [{bar}] {pct:.0f}%",
        f"📅 Deadline: {deadline} ({days} days left)",
    ]
    if remaining > 0 and days > 0:
        lines.append(f"💡 Need:     ₹{daily_needed:,.0f}/day to reach goal")
    lines += ["━" * 22, status_line]

    return "\n".join(lines)


def format_goals_list(goals: list[dict]) -> str:
    if not goals:
        return "📭 No active goals. Use /newgoal to create one!"
    parts = []
    for g in goals:
        saved  = float(g["Saved"])
        target = float(g["Target"])
        pct    = min(100.0, saved / target * 100) if target else 0
        bar    = _progress_bar(pct, width=8)
        days   = _days_left(g["Deadline"])
        parts.append(
            f"🎯 *{g['Name']}* `[{g['ID']}]`\n"
            f"   [{bar}] {pct:.0f}% • {days}d left"
        )
    return "📋 *Your Goals*\n━━━━━━━━━━━━━━━━━━━━\n" + "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Public API (called from bot.py)
# ─────────────────────────────────────────────────────────────────────────────

def cmd_new_goal(name: str, target: float, deadline_str: str, username: str) -> str:
    """
    Create a new goal.
    Returns formatted confirmation card.
    """
    goal = create_goal(name, target, deadline_str, username)
    return (
        "✅ *Goal Created!*\n\n"
        + format_goal_card(goal)
        + "\n\nUse `/deposit <ID> <amount>` to add savings."
    )


def cmd_deposit(goal_id: str, amount: float) -> str:
    goal = deposit_to_goal(goal_id.upper(), amount)
    header = (
        "🎉 *Goal Completed!*\n\n"
        if goal["Status"] == "completed"
        else f"💰 *₹{amount:,.2f} added!*\n\n"
    )
    return header + format_goal_card(goal)


def cmd_goals(username: str) -> str:
    goals = get_goals(username=username, include_done=False)
    return format_goals_list(goals)


def cmd_goal_detail(goal_id: str) -> str:
    goal = get_goal_by_id(goal_id.upper())
    if not goal:
        return f"❌ Goal `{goal_id}` not found."
    return format_goal_card(goal)


def cmd_delete_goal(goal_id: str) -> str:
    ok = delete_goal(goal_id.upper())
    if ok:
        return f"🗑️ Goal `{goal_id}` has been cancelled."
    return f"❌ Goal `{goal_id}` not found."


def cmd_all_goals(username: str) -> str:
    goals = get_goals(username=username, include_done=True)
    if not goals:
        return "📭 No goals found."
    parts = []
    for g in goals:
        saved  = float(g["Saved"])
        target = float(g["Target"])
        pct    = min(100.0, saved / target * 100) if target else 0
        emoji  = {"completed": "✅", "cancelled": "🚫", "active": "🎯"}.get(g["Status"], "🎯")
        parts.append(
            f"{emoji} *{g['Name']}* `[{g['ID']}]` — {pct:.0f}% ({g['Status']})"
        )
    return "📋 *All Goals (including past)*\n━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(parts)
