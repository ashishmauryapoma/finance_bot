"""
Utility functions — format Telegram messages for confirmations, summaries, recent transactions
"""

from datetime import datetime


CATEGORY_EMOJI = {
    "Food & Dining": "🍽️",
    "Fuel": "⛽",
    "Groceries": "🛒",
    "Transport": "🚗",
    "Utilities": "💡",
    "Rent": "🏠",
    "Healthcare": "💊",
    "Entertainment": "🎬",
    "Shopping": "🛍️",
    "Education": "📚",
    "Salary": "💼",
    "Freelance": "💻",
    "Business Income": "🏢",
    "Investment": "📈",
    "Other": "📌",
}

TYPE_EMOJI = {
    "expense": "📤",
    "income": "📥",
}


def _cat_emoji(category: str) -> str:
    return CATEGORY_EMOJI.get(category, "📌")


def _type_emoji(t: str) -> str:
    return TYPE_EMOJI.get(t.lower(), "💰")


def format_confirmation(row: dict) -> str:
    """Format a transaction confirmation message."""
    t = row.get("type", "expense").lower()
    amount = row.get("amount", 0)
    category = row.get("category", "Other")
    note = row.get("note", "")
    date = row.get("date", datetime.now().strftime("%Y-%m-%d"))

    type_label = "Expense" if t == "expense" else "Income"
    amount_fmt = f"₹{amount:,.2f}".rstrip("0").rstrip(".")

    return (
        f"{_type_emoji(t)} *Transaction Recorded!*\n"
        f"{'─' * 28}\n"
        f"📅 *Date:* {date}\n"
        f"💰 *Type:* {type_label}\n"
        f"{_cat_emoji(category)} *Category:* {category}\n"
        f"💵 *Amount:* {amount_fmt}\n"
        f"📝 *Note:* {note}\n"
        f"{'─' * 28}\n"
        f"✅ Saved to Google Sheets!"
    )


def format_recent(rows: list) -> str:
    """Format recent transactions list."""
    if not rows:
        return "📭 *No transactions found.*\n\nStart by sending a transaction like:\n`Spent 500 on petrol`"

    lines = ["📋 *Recent Transactions*\n" + "─" * 28]

    for i, row in enumerate(rows[:10], 1):
        t = str(row.get("Type", "expense")).lower()
        amount = row.get("Amount", 0)
        category = str(row.get("Category", "Other"))
        note = str(row.get("Note", ""))
        date = str(row.get("Date", ""))

        try:
            amount_fmt = f"₹{float(amount):,.0f}"
        except (ValueError, TypeError):
            amount_fmt = f"₹{amount}"

        sign = "+" if t == "income" else "-"
        emoji = _type_emoji(t)
        cat_icon = _cat_emoji(category)

        line = (
            f"{emoji} *{sign}{amount_fmt}*  {cat_icon} {category}\n"
            f"   📅 {date}  |  📝 {note[:30]}"
        )
        lines.append(line)

    lines.append("─" * 28)
    lines.append(f"_Showing last {len(rows)} transactions_")
    return "\n\n".join(lines)


def format_summary(data: dict) -> str:
    """Format monthly summary."""
    month = data.get("month", "This Month")
    income = data.get("total_income", 0)
    expense = data.get("total_expense", 0)
    net = data.get("net", 0)
    by_cat = data.get("by_category", {})

    net_emoji = "📈" if net >= 0 else "📉"
    net_label = "Surplus" if net >= 0 else "Deficit"

    lines = [
        f"📊 *Summary — {month}*\n" + "─" * 28,
        f"📥 *Total Income:*    ₹{income:,.0f}",
        f"📤 *Total Expenses:*  ₹{expense:,.0f}",
        f"{net_emoji} *Net {net_label}:*     ₹{abs(net):,.0f}",
    ]

    if by_cat:
        lines.append("\n💸 *Expenses by Category:*")
        for cat, amt in list(by_cat.items())[:8]:
            bar_len = int((amt / expense) * 10) if expense > 0 else 0
            bar = "█" * bar_len + "░" * (10 - bar_len)
            lines.append(
                f"{_cat_emoji(cat)} {cat:<18} ₹{amt:>8,.0f}  {bar}"
            )

    lines.append("─" * 28)
    return "\n".join(lines)
