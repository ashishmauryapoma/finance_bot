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
# Goals sheet (Multiple Goals Support)
# ─────────────────────────────────────────────────────────────────────────────

GOAL_HEADERS = ["Name", "Target", "Saved", "Deadline", "Created", "Status", "LastModified"]

# Purple theme for Goals sheet
_GOAL_HDR_BG = {"red": 0.494, "green": 0.239, "blue": 0.659}
_GOAL_HDR_FG = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
_GOAL_ROW_BG = {"red": 0.965, "green": 0.941, "blue": 0.984}  # light lavender


def clear_goal_cache():
    """Explicitly clear the goal sheet cache to force reload from Google Sheets."""
    global _goal_sheet
    _goal_sheet = None


def _get_goal_sheet():
    global _goal_sheet
    if _goal_sheet:
        return _goal_sheet

    ws = _get_or_create("Goals", rows=1000, cols=10)

    existing = ws.row_values(1)
    
    # If sheet is empty or headers don't match, initialize with proper headers
    if not existing or existing != GOAL_HEADERS:
        ws.clear()
        ws.update("A1", [GOAL_HEADERS], value_input_option="RAW")
        _style_goal_header(ws)
    else:
        # Verify all 7 columns are present in existing data
        # If LastModified column (column 7) is missing, initialize it for existing rows
        all_rows = ws.get_all_values()
        if len(all_rows) > 1:  # Has data beyond header
            needs_update = False
            for i, row in enumerate(all_rows[1:], start=2):
                # Pad row if it doesn't have all 7 columns
                if len(row) < len(GOAL_HEADERS):
                    # For missing LastModified column, use Created timestamp (column 5)
                    created_timestamp = row[4] if len(row) > 4 else ""
                    while len(row) < len(GOAL_HEADERS):
                        row.append(created_timestamp if len(row) == 6 else "")
                    ws.update(f"A{i}:G{i}", [row], value_input_option="RAW")
                    needs_update = True
            if needs_update:
                _style_goal_header(ws)

    _goal_sheet = ws
    return ws


def _style_goal_header(ws):
    """Apply purple header styling to all 7 columns of the Goals sheet."""
    ss  = _connect()
    sid = ws.id

    # Column widths for all 7 columns: Name, Target, Saved, Deadline, Created, Status, LastModified
    col_pxs = [180, 110, 110, 120, 120, 100, 120]

    requests = [
        _freeze_request(sid, rows=1),
    ]
    
    # Apply column widths for all 7 columns
    requests += [_col_width_request(sid, i, px) for i, px in enumerate(col_pxs)]
    
    # Set header row height
    requests.append(_row_height_request(sid, 0, 1, 32))
    
    # Apply purple header styling to all 7 columns
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sid,
                "startRowIndex": 0,
                "endRowIndex": 1,
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
    })
    
    ss.batch_update({"requests": requests})
    logger.info("Goal sheet header styled")


def _style_goal_data_rows(ws, start_row: int = 2, end_row: int = 3):
    """
    Style data rows of the Goals sheet with all 7 columns.
    Apply alternating row background colors, bold right-aligned saved amounts, and borders.
    """
    ss  = _connect()
    sid = ws.id

    # Apply base styling (background + borders) to all 7 columns
    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": sid,
                "startRowIndex": start_row - 1,
                "endRowIndex": end_row,
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
    
    # Apply special styling to Saved column (index 2): bold and right-aligned
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sid,
                "startRowIndex": start_row - 1,
                "endRowIndex": end_row,
                "startColumnIndex": 2,  # Saved column
                "endColumnIndex": 3,
            },
            "cell": {
                "userEnteredFormat": {
                    **_cell_fmt(bg=_GOAL_ROW_BG, bold=True, h_align="RIGHT", font_size=10),
                    "borders": _full_border(),
                }
            },
            "fields": "userEnteredFormat",
        }
    })
    
    ss.batch_update({"requests": requests})


# ─────────────────────────────────────────────────────────────────────────────
# Public Goal API — Multiple Goals
# ─────────────────────────────────────────────────────────────────────────────

def get_all_goals_multi(status_filter: str = None) -> list[dict]:
    """
    Get all goals from the Goals sheet.
    status_filter: None (all), "active", "completed", "deleted"
    Returns a list of goal dicts sorted by Created date (newest first).
    Each dict has keys: Name, Target, Saved, Deadline, Created, Status, LastModified
    """
    ws   = _get_goal_sheet()
    rows = ws.get_all_values()
    
    if len(rows) < 2:
        return []
    
    goals = []
    for row in rows[1:]:
        if not any(row):  # skip empty rows
            continue
        if len(row) < len(GOAL_HEADERS):
            row = row + [""] * (len(GOAL_HEADERS) - len(row))
        goal = dict(zip(GOAL_HEADERS, row))
        
        if status_filter:
            if goal.get("Status", "").strip().lower() != status_filter.lower():
                continue
        
        goals.append(goal)
    
    # Sort by Created date (newest first)
    goals.sort(key=lambda g: g.get("Created", ""), reverse=True)
    return goals


def get_all_goals(status_filter: str = None) -> list[dict]:
    """
    Get all goals from the Goals sheet.
    Backward compatibility wrapper for get_all_goals_multi().
    """
    return get_all_goals_multi(status_filter)


def get_goal_by_name_multi(name: str) -> dict | None:
    """
    Get a specific goal by exact name (case-insensitive).
    Excludes deleted goals from the search.
    Returns goal dict with all 7 columns if found, None otherwise.
    """
    goals = get_all_goals_multi()
    name_lower = name.strip().lower()
    for goal in goals:
        status = goal.get("Status", "").strip().lower()
        # Skip deleted goals
        if status == "deleted":
            continue
        if goal.get("Name", "").strip().lower() == name_lower:
            return goal
    return None


def get_goal_by_name(name: str) -> dict | None:
    """Get a specific goal by name (case-insensitive). Returns None if not found."""
    return get_goal_by_name_multi(name)


def validate_goal_uniqueness(name: str) -> bool:
    """
    Check if goal with given name already exists (case-insensitive).
    Returns True if name is unique and can be used.
    Returns False if name already exists.
    """
    return get_goal_by_name_multi(name) is None


def find_similar_goals(goal_name: str, max_suggestions: int = 3) -> list[dict]:
    """
    Find goals with names similar to the given name (case-insensitive substring match).
    Returns list of matching goals sorted by similarity.
    Used for suggesting goals when exact match is not found.
    """
    from difflib import SequenceMatcher
    
    goal_name_lower = goal_name.strip().lower()
    all_goals = get_all_goals()
    
    # Filter goals that match the search criteria
    matching = []
    for goal in all_goals:
        name_lower = goal.get("Name", "").strip().lower()
        status = goal.get("Status", "").strip().lower()
        
        # Only suggest active and completed goals (not deleted)
        if status == "deleted":
            continue
        
        # Check if goal name contains search term or vice versa (substring match)
        if goal_name_lower in name_lower or name_lower in goal_name_lower:
            similarity = SequenceMatcher(None, goal_name_lower, name_lower).ratio()
            matching.append((goal, similarity))
    
    # Sort by similarity (highest first)
    matching.sort(key=lambda x: x[1], reverse=True)
    
    return [goal for goal, _ in matching[:max_suggestions]]


def get_active_goals() -> list[dict]:
    """Get all active (non-completed, non-deleted) goals."""
    return get_all_goals(status_filter="active")


def get_completed_goals() -> list[dict]:
    """Get all completed goals."""
    return get_all_goals(status_filter="completed")


def create_goal(name: str, target: float, deadline: str = "") -> dict:
    """
    Create a new goal and append it to the Goals sheet.
    Multiple goals are supported — no replacement.
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
        now_ist,
    ]

    ws.append_row(row, value_input_option="RAW")
    
    _goal_sheet = None  # invalidate cache
    
    # Style the new row
    all_rows = ws.get_all_values()
    new_row_idx = len(all_rows)
    _style_goal_data_rows(ws, start_row=new_row_idx, end_row=new_row_idx + 1)
    
    return get_goal_by_name(name) or dict(zip(GOAL_HEADERS, row))


def add_to_goal(goal_name: str, amount: float, username: str = "goal") -> tuple[dict | None, bool]:
    """
    Add amount toward a specific goal's Saved total (by goal name).
    
    - Only accepts deposits up to the remaining amount needed (target - saved).
    - Logs every deposit as a 'Goal Saving' expense transaction.
    - On completion, marks status as "completed" but does NOT auto-book income.
    
    Returns (updated_goal_dict, just_completed).
    Returns (None, False) if goal not found or already completed.
    """
    global _goal_sheet
    ws = _get_goal_sheet()
    
    goal = get_goal_by_name(goal_name)
    if not goal:
        return None, False
    
    status = goal.get("Status", "").strip().lower()
    if status != "active":
        return None, False
    
    prev_saved = float(goal.get("Saved", 0))
    target     = float(goal.get("Target", 0))
    
    # Cap the deposit at the remaining amount needed
    remaining = round(target - prev_saved, 2)
    deposit   = round(min(amount, remaining), 2)
    new_saved = round(prev_saved + deposit, 2)
    
    # ── 1. Find and update the goal row in the sheet ────────────────────────
    all_rows = ws.get_all_values()
    goal_row_idx = None
    
    for i, row in enumerate(all_rows[1:], start=2):  # start from row 2
        if len(row) > 0 and row[0].strip().lower() == goal_name.strip().lower():
            goal_row_idx = i
            break
    
    if goal_row_idx is None:
        return None, False
    
    # Update Saved amount
    ws.update(f"C{goal_row_idx}", [[new_saved]], value_input_option="RAW")
    
    # Update LastModified
    now_ist = datetime.now(_IST).strftime("%d-%m-%Y")
    ws.update(f"G{goal_row_idx}", [[now_ist]], value_input_option="RAW")
    
    just_completed = new_saved >= target
    if just_completed:
        ws.update(f"F{goal_row_idx}", [["completed"]], value_input_option="RAW")
    
    _goal_sheet = None  # invalidate cache
    
    # ── 2. Log deposit as a transaction (Goal Saving) ────────────────────────
    now_ist = datetime.now(_IST)
    deposit_row = {
        "date":      now_ist.strftime("%d-%m-%Y"),
        "timestamp": now_ist.strftime("%I:%M:%S %p"),
        "type":      "expense",
        "category":  "Goal Saving",
        "amount":    deposit,
        "note":      f"Saved toward: {goal_name}",
        "user":      username,
    }
    append_transaction(deposit_row)
    
    # Return updated goal
    goal["Saved"] = str(new_saved)
    if just_completed:
        goal["Status"] = "completed"
    goal["LastModified"] = now_ist.strftime("%d-%m-%Y")
    
    return goal, just_completed


def break_goal(goal_name: str, username: str = "goal") -> bool:
    """
    Delete/break a goal and refund any saved amount to net balance as 'Goal Refund' income.
    Marks the goal as "deleted" instead of removing the row.
    """
    global _goal_sheet
    ws = _get_goal_sheet()
    
    goal = get_goal_by_name(goal_name)
    if not goal:
        return False
    
    saved = float(goal.get("Saved", 0))
    
    # Find and update the goal row
    all_rows = ws.get_all_values()
    goal_row_idx = None
    
    for i, row in enumerate(all_rows[1:], start=2):
        if len(row) > 0 and row[0].strip().lower() == goal_name.strip().lower():
            goal_row_idx = i
            break
    
    if goal_row_idx is None:
        return False
    
    # Mark as deleted
    now_ist = datetime.now(_IST).strftime("%d-%m-%Y")
    ws.update(f"F{goal_row_idx}", [["deleted"]], value_input_option="RAW")
    ws.update(f"G{goal_row_idx}", [[now_ist]], value_input_option="RAW")
    
    # Force cache invalidation by setting global variable to None
    global _goal_sheet
    _goal_sheet = None
    
    # If amount was saved, log it as refund income
    if saved > 0:
        now_ist_full = datetime.now(_IST)
        refund_row = {
            "date":      now_ist_full.strftime("%d-%m-%Y"),
            "timestamp": now_ist_full.strftime("%I:%M:%S %p"),
            "type":      "income",
            "category":  "Goal Refund",
            "amount":    round(saved, 2),
            "note":      f"Broken goal: {goal_name} (amount returned to balance)",
            "user":      username,
        }
        append_transaction(refund_row)
    
    return True
