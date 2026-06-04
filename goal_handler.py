"""
Goal Tracker — single active goal at a time.
Stores goal data in a 'Goals' tab in the same Google Sheet.
"""

from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))

# Column layout in the Goals sheet (1 data row, row 2)
# | Name | Target | Saved | Deadline | Created | Status |
GOAL_HEADERS = ["Name", "Target", "Saved", "Deadline", "Created", "Status"]


# ─────────────────────────────────────────────────────────────────────────────
# Progress bar helper
# ─────────────────────────────────────────────────────────────────────────────

def make_progress_bar(saved: float, target: float, length: int = 10) -> str:
    percent = min(saved / target, 1.0) if target > 0 else 0
    filled  = int(percent * length)
    bar     = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent * 100:.1f}%"


def _days_left(deadline_str: str) -> int | None:
    """Return days remaining to deadline, or None if no deadline."""
    if not deadline_str or deadline_str.strip() == "":
        return None
    try:
        deadline = datetime.strptime(deadline_str.strip(), "%Y-%m-%d")
        today    = datetime.now(_IST).replace(tzinfo=None)
        return max((deadline - today).days, 0)
    except ValueError:
        return None


def _daily_needed(saved: float, target: float, deadline_str: str) -> str | None:
    days = _days_left(deadline_str)
    if not days or days == 0:
        return None
    remaining = target - saved
    if remaining <= 0:
        return None
    return f"₹{remaining / days:,.0f}/day"


# ─────────────────────────────────────────────────────────────────────────────
# Format goal card (the premium-looking message)
# ─────────────────────────────────────────────────────────────────────────────

def format_goal_card(goal: dict) -> str:
    name     = goal.get("Name", "")
    target   = float(goal.get("Target", 0))
    saved    = float(goal.get("Saved", 0))
    deadline = goal.get("Deadline", "")

    bar      = make_progress_bar(saved, target)
    days     = _days_left(deadline)
    needed   = _daily_needed(saved, target, deadline)
    on_track = ""

    if days is not None and needed:
        on_track = f"\n💡 *Need:*      {needed} to reach goal"
    elif days is not None and saved >= target:
        on_track = "\n🏆 *Goal complete!* Time to make it happen!"

    deadline_line = ""
    if deadline:
        days_text = f"({days} days left)" if days is not None else ""
        deadline_line = f"\n📅 *Deadline:* {deadline} {days_text}"

    return (
        f"🎯 *{name}*\n"
        f"{'━' * 28}\n"
        f"💰 *Saved:*    ₹{saved:,.2f} / ₹{target:,.2f}\n"
        f"📊 *Progress:* {bar}"
        f"{deadline_line}"
        f"{on_track}\n"
        f"{'━' * 28}"
    )


def format_goal_complete(goal: dict) -> str:
    name   = goal.get("Name", "")
    target = float(goal.get("Target", 0))
    return (
        f"🏆 *Goal Complete!*\n"
        f"{'━' * 28}\n"
        f"🎉 You've saved ₹{target:,.2f} for *{name}*!\n"
        f"Time to make it happen! 🚀\n"
        f"{'━' * 28}"
    )
