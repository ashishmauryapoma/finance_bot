"""
goal_handler.py — Goal Tracker helpers
Formatting and progress bar logic for the single active goal feature.
"""

from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))


# ─────────────────────────────────────────────────────────────────────────────
# Progress bar
# ─────────────────────────────────────────────────────────────────────────────

def make_progress_bar(saved: float, target: float, length: int = 10) -> str:
    percent = min(saved / target, 1.0) if target > 0 else 0.0
    filled  = int(percent * length)
    bar     = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent * 100:.1f}%"


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _days_left(deadline_str: str) -> int | None:
    """Return days remaining to deadline, or None if no deadline set."""
    if not deadline_str or not deadline_str.strip():
        return None
    try:
        deadline = datetime.strptime(deadline_str.strip(), "%Y-%m-%d")
        today    = datetime.now(_IST).replace(tzinfo=None)
        return max((deadline - today).days, 0)
    except ValueError:
        return None


def _daily_needed(saved: float, target: float, deadline_str: str) -> str | None:
    """Return daily saving amount needed as formatted string, or None."""
    days = _days_left(deadline_str)
    if not days or days == 0:
        return None
    remaining = target - saved
    if remaining <= 0:
        return None
    return f"₹{remaining / days:,.0f}/day"


# ─────────────────────────────────────────────────────────────────────────────
# Message formatters
# ─────────────────────────────────────────────────────────────────────────────

def format_goal_card(goal: dict) -> str:
    """Return a premium-styled progress card for the given goal dict."""
    name     = goal.get("Name", "")
    target   = float(goal.get("Target", 0))
    saved    = float(goal.get("Saved", 0))
    deadline = goal.get("Deadline", "")

    bar    = make_progress_bar(saved, target)
    days   = _days_left(deadline)
    needed = _daily_needed(saved, target, deadline)

    # Deadline line
    deadline_line = ""
    if deadline and deadline.strip():
        days_text     = f"({days} days left)" if days is not None else ""
        deadline_line = f"\n📅 *Deadline:* {deadline} {days_text}"

    # On-track hint
    on_track = ""
    if saved >= target:
        on_track = "\n🏆 *Goal complete!* Time to make it happen!"
    elif needed:
        on_track = f"\n💡 *Need:*      {needed} to reach goal"

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
    """Return a celebration message when a goal is fully funded."""
    name   = goal.get("Name", "")
    target = float(goal.get("Target", 0))
    return (
        f"🏆 *Goal Complete!*\n"
        f"{'━' * 28}\n"
        f"🎉 You've saved ₹{target:,.2f} for *{name}*!\n"
        f"Time to make it happen! 🚀\n"
        f"{'━' * 28}"
    )
