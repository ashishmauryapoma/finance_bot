"""
Google Sheets handler — read and write financial transactions
- Transactions sheet: styled table with bold headers, alternating row colors, borders
- Summary sheet: auto-updated summary table with totals by category
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))

import gspread
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = ["Date", "Timestamp", "Type", "Category", "Amount", "Note", "User"]

# ── Styling constants ─────────────────────────────────────────────────────────
HEADER_BG        = {"red": 0.157, "green": 0.306, "blue": 0.612}   # deep blue
HEADER_FG        = {"red": 1.0,   "green": 1.0,   "blue": 1.0}     # white
ROW_ALT_BG       = {"red": 0.906, "green": 0.925, "blue": 0.969}   # light blue-gray
ROW_NORMAL_BG    = {"red": 1.0,   "green": 1.0,   "blue": 1.0}     # white
INCOME_FG        = {"red": 0.106, "green": 0.533, "blue": 0.196}   # green
EXPENSE_FG       = {"red": 0.741, "green": 0.149, "blue": 0.133}   # red

_client      = None
_spreadsheet = None
_txn_sheet   = None
_goal_sheet  = None


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _connect():
    global _client, _spreadsheet
    if _spreadsheet:
        return _spreadsheet

    creds_path      = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    spreadsheet_id  = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        raise ValueError("SPREADSHEET_ID not set.")

    creds        = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    _client      = gspread.authorize(creds)
    _spreadsheet = _client.open_by_key(spreadsheet_id)
    return _spreadsheet


def _get_or_create(name: str, rows: int = 1000, cols: int = 20):
    ss = _connect()
    try:
        return ss.worksheet(name)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=name, rows=rows, cols=cols)


def _border_side(style="SOLID", width=1, color=None):
    color = color or {"red": 0.7, "green": 0.7, "blue": 0.7}
    return {"style": style, "width": width, "color": color}


def _full_border(style="SOLID", width=1, color=None):
    side = _border_side(style, width, color)
    return {"top": side, "bottom": side, "left": side, "right": side}


def _cell_fmt(bg=None, fg=None, bold=False, h_align="LEFT", font_size=10):
    fmt = {
        "textFormat": {
            "bold": bold,
            "fontSize": font_size,
        },
        "horizontalAlignment": h_align,
    }
    if bg:
        fmt["backgroundColor"] = bg
    if fg:
        fmt["textFormat"]["foregroundColor"] = fg
    return fmt


def _col_width_request(sheet_id: int, col_index: int, px: int):
    return {
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": col_index,
                "endIndex": col_index + 1,
            },
            "properties": {"pixelSize": px},
            "fields": "pixelSize",
        }
    }


def _row_height_request(sheet_id: int, start: int, end: int, px: int):
    return {
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "ROWS",
                "startIndex": start,
                "endIndex": end,
            },
            "properties": {"pixelSize": px},
            "fields": "pixelSize",
        }
    }


def _freeze_request(sheet_id: int, rows: int = 1, cols: int = 0):
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": rows, "frozenColumnCount": cols},
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Transactions sheet
# ─────────────────────────────────────────────────────────────────────────────

def _get_txn_sheet():
    global _txn_sheet
    if _txn_sheet:
        return _txn_sheet

    sheet_name = os.getenv("SHEET_NAME", "Transactions")
    ws = _get_or_create(sheet_name)

    existing = ws.row_values(1)
    if existing != HEADERS:
        ws.insert_row(HEADERS, 1)

    _apply_txn_header_style(ws)
    _txn_sheet = ws
    return ws


def _apply_txn_header_style(ws):
    """Bold colored header row + freeze + column widths + force text format on date/timestamp."""
    ss      = _connect()
    sid     = ws.id
    col_pxs = [110, 130, 90, 140, 100, 220, 110]   # Date, Timestamp, Type, Category, Amount, Note, User

    requests = [_freeze_request(sid, rows=1)]
    requests += [_col_width_request(sid, i, px) for i, px in enumerate(col_pxs)]
    requests.append(_row_height_request(sid, 0, 1, 32))  # header row height

    # Header cell formatting
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": len(HEADERS)},
            "cell": {
                "userEnteredFormat": {
                    **_cell_fmt(bg=HEADER_BG, fg=HEADER_FG, bold=True,
                                h_align="CENTER", font_size=11),
                    "borders": _full_border("SOLID", 2,
                                            {"red": 0.1, "green": 0.2, "blue": 0.5}),
                }
            },
            "fields": "userEnteredFormat",
        }
    })

    # Force Date column (A) to plain text format so dd-mm-yyyy stays as string
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 1000,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "TEXT"}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    })

    # Force Timestamp column (B, index 1) to plain text
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 1000,
                      "startColumnIndex": 1, "endColumnIndex": 2},
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "TEXT"}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    })

    ss.batch_update({"requests": requests})
    logger.info("Transaction sheet header styled")


def _style_new_row(ws, row_index: int, row_type: str):
    """
    Apply alternating background + income/expense color to a newly added data row.
    row_index is 1-based (same as gspread row numbers).
    """
    ss  = _connect()
    sid = ws.id
    ri  = row_index - 1          # 0-based for API

    bg  = ROW_ALT_BG if row_index % 2 == 0 else ROW_NORMAL_BG
    amt_fg = INCOME_FG if row_type == "income" else EXPENSE_FG

    # Entire row background
    requests = [{
        "repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": ri, "endRowIndex": ri + 1,
                      "startColumnIndex": 0, "endColumnIndex": len(HEADERS)},
            "cell": {
                "userEnteredFormat": {
                    **_cell_fmt(bg=bg, font_size=10),
                    "borders": _full_border(),
                }
            },
            "fields": "userEnteredFormat",
        }
    }]

    # Amount column (index 4) gets colored text
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": ri, "endRowIndex": ri + 1,
                      "startColumnIndex": 4, "endColumnIndex": 5},
            "cell": {
                "userEnteredFormat": {
                    **_cell_fmt(bg=bg, fg=amt_fg, bold=True,
                                h_align="RIGHT", font_size=10),
                    "borders": _full_border(),
                }
            },
            "fields": "userEnteredFormat",
        }
    })

    ss.batch_update({"requests": requests})


# ─────────────────────────────────────────────────────────────────────────────
# Goals sheet
# ─────────────────────────────────────────────────────────────────────────────

def append_transaction(row: dict):
    """Append a transaction row, style it, then refresh the Summary sheet."""
    ws = _get_txn_sheet()

    now_ist = datetime.now(_IST)

    # Safely parse amount — Groq sometimes returns a string
    try:
        amount = float(str(row.get("amount", 0)).replace(",", "").strip())
    except (ValueError, TypeError):
        amount = 0.0

    values = [
        row.get("date", now_ist.strftime("%d-%m-%Y")),
        row.get("timestamp", now_ist.strftime("%I:%M:%S %p")),   # time only, 12-hr
        row.get("type", "expense").strip().lower(),
        row.get("category", "Other").strip(),
        round(amount, 2),
        row.get("note", ""),
        row.get("user", ""),
    ]

    ws.append_row(values, value_input_option="RAW")

    # Style the new row
    all_values  = ws.get_all_values()
    new_row_idx = len(all_values)          # 1-based
    _style_new_row(ws, new_row_idx, row.get("type", "expense"))



    logger.info(f"Transaction appended: {values}")


def get_recent_transactions(user_id: str = None, limit: int = 10) -> list[dict]:
    ws       = _get_txn_sheet()
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return []
    header   = all_values[0]
    data     = all_values[1:]
    records  = [dict(zip(header, row)) for row in data]
    return list(reversed(records))[:limit]


def get_summary(user_id: str = None) -> dict:
    ws          = _get_txn_sheet()
    all_values  = ws.get_all_values()
    cur_month   = datetime.now(_IST).strftime("%m-%Y")

    total_income = total_expense = 0.0
    by_category  = defaultdict(float)

    if len(all_values) >= 2:
        header = [h.strip().lower() for h in all_values[0]]
        try:
            i_date = header.index("date")
            i_type = header.index("type")
            i_cat  = header.index("category")
            i_amt  = header.index("amount")
        except ValueError:
            i_date, i_type, i_cat, i_amt = 0, 2, 3, 4

        for row in all_values[1:]:
            if len(row) <= i_amt:
                continue
            date_str = row[i_date].strip()
            if len(date_str) < 7 or date_str[3:] != cur_month:
                continue
            try:
                amt = float(row[i_amt])
            except (ValueError, TypeError):
                continue
            t   = row[i_type].strip().lower()
            cat = row[i_cat].strip() or "Other"
            if t == "income":
                total_income += amt
            else:
                total_expense += amt
                by_category[cat] += amt

    return {
        "month":         datetime.now(_IST).strftime("%B %Y"),
        "total_income":  total_income,
        "total_expense": total_expense,
        "net":           total_income - total_expense,
        "by_category":   dict(sorted(by_category.items(),
                                     key=lambda x: x[1], reverse=True)),
    }


def get_balance(user_id: str = None) -> dict:
    """
    Return a running balance breakdown:
    - All-time total income, total expense, net balance
    - Current month income, expense, net
    - Largest expense category this month
    """
    ws         = _get_txn_sheet()
    all_values = ws.get_all_values()
    cur_month  = datetime.now(_IST).strftime("%m-%Y")

    all_income = all_expense = 0.0
    month_income = month_expense = 0.0
    month_cats: dict = defaultdict(float)

    if len(all_values) >= 2:
        header = [h.strip().lower() for h in all_values[0]]
        try:
            i_date = header.index("date")
            i_type = header.index("type")
            i_cat  = header.index("category")
            i_amt  = header.index("amount")
        except ValueError:
            i_date, i_type, i_cat, i_amt = 0, 2, 3, 4

        for row in all_values[1:]:
            if len(row) <= i_amt:
                continue
            try:
                amt = float(row[i_amt])
            except (ValueError, TypeError):
                continue
            t        = row[i_type].strip().lower()
            date_str = row[i_date].strip()
            cat      = row[i_cat].strip() or "Other"
            is_month = len(date_str) >= 7 and date_str[3:] == cur_month

            if t == "income":
                all_income += amt
                if is_month:
                    month_income += amt
            else:
                all_expense += amt
                if is_month:
                    month_expense += amt
                    month_cats[cat] += amt

    top_cat = max(month_cats, key=month_cats.get) if month_cats else "—"
    top_cat_amt = month_cats.get(top_cat, 0)

    return {
        "month":          datetime.now(_IST).strftime("%B %Y"),
        "all_income":     all_income,
        "all_expense":    all_expense,
        "net_balance":    all_income - all_expense,
        "month_income":   month_income,
        "month_expense":  month_expense,
        "month_net":      month_income - month_expense,
        "top_category":   top_cat,
        "top_cat_amount": top_cat_amt,
    }





# ─────────────────────────────────────────────────────────────────────────────
# Goals sheet
# ─────────────────────────────────────────────────────────────────────────────

GOAL_HEADERS = ["Name", "Target", "Saved", "Deadline", "Created", "Status"]

# Purple theme for Goals sheet
_GOAL_HDR_BG = {"red": 0.494, "green": 0.239, "blue": 0.659}
_GOAL_HDR_FG = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
_GOAL_ROW_BG = {"red": 0.965, "green": 0.941, "blue": 0.984}  # light lavender


def _get_goal_sheet():
    global _goal_sheet
    if _goal_sheet:
        return _goal_sheet

    ws = _get_or_create("Goals", rows=10, cols=10)

    existing = ws.row_values(1)
    if existing != GOAL_HEADERS:
        ws.clear()
        ws.update("A1", [GOAL_HEADERS], value_input_option="RAW")
        _style_goal_header(ws)

    _goal_sheet = ws
    return ws


def _style_goal_header(ws):
    """Apply purple header styling to the Goals sheet."""
    ss  = _connect()
    sid = ws.id

    requests = [
        _freeze_request(sid, rows=1),
        _col_width_request(sid, 0, 180),
        _col_width_request(sid, 1, 110),
        _col_width_request(sid, 2, 110),
        _col_width_request(sid, 3, 120),
        _col_width_request(sid, 4, 120),
        _col_width_request(sid, 5, 100),
        _row_height_request(sid, 0, 1, 32),
        {
            "repeatCell": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(GOAL_HEADERS),
                },
                "cell": {
                    "userEnteredFormat": {
                        **_cell_fmt(bg=_GOAL_HDR_BG, fg=_GOAL_HDR_FG,
                                    bold=True, h_align="CENTER", font_size=11),
                        "borders": _full_border(
                            "SOLID", 2, {"red": 0.3, "green": 0.1, "blue": 0.5}
                        ),
                    }
                },
                "fields": "userEnteredFormat",
            }
        },
    ]
    ss.batch_update({"requests": requests})
    logger.info("Goal sheet header styled")


def _style_goal_data_row(ws):
    """Style the single data row (row 2) of the Goals sheet."""
    ss  = _connect()
    sid = ws.id

    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": sid,
                "startRowIndex": 1, "endRowIndex": 2,
                "startColumnIndex": 0,
                "endColumnIndex": len(GOAL_HEADERS),
            },
            "cell": {
                "userEnteredFormat": {
                    **_cell_fmt(bg=_GOAL_ROW_BG, font_size=10),
                    "borders": _full_border(),
                }
            },
            "fields": "userEnteredFormat",
        }
    }]
    ss.batch_update({"requests": requests})


# ─────────────────────────────────────────────────────────────────────────────
# Public Goal API
# ─────────────────────────────────────────────────────────────────────────────

def get_goal() -> dict | None:
    """Return the current active goal as a dict, or None if no active goal."""
    ws   = _get_goal_sheet()
    rows = ws.get_all_values()
    if len(rows) < 2 or not any(rows[1]):
        return None
    goal = dict(zip(GOAL_HEADERS, rows[1]))
    if goal.get("Status", "").strip().lower() != "active":
        return None
    return goal


def create_goal(name: str, target: float, deadline: str = "") -> dict:
    """
    Create a new goal, overwriting any existing one (only one at a time).
    deadline should be 'YYYY-MM-DD' or empty string.
    Returns the newly created goal dict.
    """
    global _goal_sheet
    ws      = _get_goal_sheet()
    now_ist = datetime.now(_IST).strftime("%d-%m-%Y")

    row = [
        name.strip(),
        round(target, 2),
        0.0,
        deadline.strip(),
        now_ist,
        "active",
    ]

    all_rows = ws.get_all_values()
    if len(all_rows) >= 2:
        ws.update("A2", [row], value_input_option="RAW")
    else:
        ws.append_row(row, value_input_option="RAW")

    _goal_sheet = None  # invalidate cache so get_goal re-reads fresh data
    _style_goal_data_row(_get_goal_sheet())
    return get_goal()


def add_to_goal(amount: float, username: str = "goal") -> tuple[dict | None, bool]:
    """
    Add amount to the current goal's Saved total.

    - Logs every deposit as a 'Goal Saving' expense transaction so the
      money trail is visible in the Transactions sheet.
    - When the goal is fully funded, auto-logs the entire saved amount
      as an Income transaction ('Goal Achieved') so it flows into
      /balance and /summary automatically.

    Returns (updated_goal_dict, just_completed).
    Returns (None, False) if no active goal exists.
    """
    global _goal_sheet
    ws   = _get_goal_sheet()
    goal = get_goal()
    if not goal:
        return None, False

    goal_name = goal.get("Name", "Goal")
    prev_saved = float(goal.get("Saved", 0))
    target     = float(goal.get("Target", 0))
    new_saved  = round(prev_saved + amount, 2)

    # ── 1. Update the Goals sheet ────────────────────────────────────────────
    ws.update("C2", [[new_saved]], value_input_option="RAW")

    just_completed = (prev_saved < target) and (new_saved >= target)
    if just_completed:
        ws.update("F2", [["completed"]], value_input_option="RAW")

    _goal_sheet = None  # invalidate cache

    # ── 2. Log deposit as a transaction (Goal Saving) ────────────────────────
    now_ist = datetime.now(_IST)
    deposit_row = {
        "date":      now_ist.strftime("%d-%m-%Y"),
        "timestamp": now_ist.strftime("%I:%M:%S %p"),
        "type":      "expense",
        "category":  "Goal Saving",
        "amount":    round(amount, 2),
        "note":      f"Saved toward: {goal_name}",
        "user":      username,
    }
    append_transaction(deposit_row)

    # ── 3. On completion, log full saved amount as income ────────────────────
    if just_completed:
        income_row = {
            "date":      now_ist.strftime("%d-%m-%Y"),
            "timestamp": now_ist.strftime("%I:%M:%S %p"),
            "type":      "income",
            "category":  "Goal Achieved",
            "amount":    round(new_saved, 2),
            "note":      f"Goal completed: {goal_name}",
            "user":      username,
        }
        append_transaction(income_row)

    return get_goal(), just_completed


def delete_goal(username: str = "goal") -> bool:
    """
    Clear the current goal row.
    If any amount was already saved, log it as income so the deposited
    money flows back into the user's net balance.
    """
    global _goal_sheet
    ws   = _get_goal_sheet()
    goal = get_goal()

    if goal:
        saved     = float(goal.get("Saved", 0))
        goal_name = goal.get("Name", "Goal")
        if saved > 0:
            now_ist = datetime.now(_IST)
            refund_row = {
                "date":      now_ist.strftime("%d-%m-%Y"),
                "timestamp": now_ist.strftime("%I:%M:%S %p"),
                "type":      "income",
                "category":  "Goal Refund",
                "amount":    round(saved, 2),
                "note":      f"Goal deleted: {goal_name} (deposited amount refunded)",
                "user":      username,
            }
            append_transaction(refund_row)

    ws.update("A2:F2", [["", "", "", "", "", ""]], value_input_option="RAW")
    _goal_sheet = None
    return True
