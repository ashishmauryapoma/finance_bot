"""
Google Sheets handler — read and write financial transactions
Uses gspread with service account credentials
"""

import os
import logging
from datetime import datetime
from collections import defaultdict

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Google Sheets scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Column headers (must match sheet exactly)
HEADERS = ["Date", "Type", "Category", "Amount", "Note", "User", "Timestamp"]

_client = None
_sheet = None


def _get_sheet():
    """Initialize and return the Google Sheet worksheet."""
    global _client, _sheet

    if _sheet is not None:
        return _sheet

    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    sheet_name = os.getenv("SHEET_NAME", "Transactions")

    if not spreadsheet_id:
        raise ValueError("SPREADSHEET_ID not set in environment variables.")

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    _client = gspread.authorize(creds)

    spreadsheet = _client.open_by_key(spreadsheet_id)

    # Get or create sheet
    try:
        _sheet = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        _sheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
        # Add headers
        _sheet.append_row(HEADERS)
        logger.info(f"Created new sheet: {sheet_name} with headers")

    # Ensure headers exist on row 1
    existing = _sheet.row_values(1)
    if existing != HEADERS:
        _sheet.insert_row(HEADERS, 1)
        logger.info("Headers inserted into sheet")

    return _sheet


def append_transaction(row: dict):
    """
    Append a single transaction row to the Google Sheet.
    
    row keys: date, type, category, amount, note, user, timestamp
    """
    sheet = _get_sheet()

    values = [
        row.get("date", ""),
        row.get("type", "expense"),
        row.get("category", "Other"),
        row.get("amount", 0),
        row.get("note", ""),
        row.get("user", ""),
        row.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]

    sheet.append_row(values, value_input_option="USER_ENTERED")
    logger.info(f"Appended transaction: {values}")


def get_recent_transactions(user_id: str = None, limit: int = 10) -> list[dict]:
    """
    Fetch recent transactions from the sheet.
    Optionally filter by username.
    Returns list of dicts matching HEADERS.
    """
    sheet = _get_sheet()
    all_rows = sheet.get_all_records()

    # Most recent first
    all_rows = list(reversed(all_rows))

    if not all_rows:
        return []

    return all_rows[:limit]


def get_summary(user_id: str = None) -> dict:
    """
    Calculate summary for the current month.
    Returns: { total_income, total_expense, net, by_category: {cat: amount} }
    """
    sheet = _get_sheet()
    all_rows = sheet.get_all_records()

    current_month = datetime.now().strftime("%Y-%m")

    total_income = 0.0
    total_expense = 0.0
    by_category = defaultdict(float)

    for row in all_rows:
        date_str = str(row.get("Date", ""))
        if not date_str.startswith(current_month):
            continue

        try:
            amount = float(row.get("Amount", 0))
        except (ValueError, TypeError):
            continue

        t = str(row.get("Type", "")).lower()
        cat = str(row.get("Category", "Other"))

        if t == "income":
            total_income += amount
        else:
            total_expense += amount
            by_category[cat] += amount

    return {
        "month": datetime.now().strftime("%B %Y"),
        "total_income": total_income,
        "total_expense": total_expense,
        "net": total_income - total_expense,
        "by_category": dict(sorted(by_category.items(), key=lambda x: x[1], reverse=True)),
    }
