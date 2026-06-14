"""
Google Sheets handler — read and write financial transactions
Sheets created / managed:
  1. Transactions  – styled table with bold headers, alternating row colors,
                     borders, running-balance column
  2. Dashboard     – live KPI cards (income / expense / net / savings rate)
                     + top-5 expense categories + recent 5 transactions
  3. Monthly       – month-by-month pivot (income, expense, net per month)
  4. Goals         – single active goal tracker (purple theme)
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = ["Date", "Timestamp", "Type", "Category", "Amount", "Note", "User", "Balance"]

# ── Colour palette ────────────────────────────────────────────────────────────
HEADER_BG     = {"red": 0.114, "green": 0.208, "blue": 0.380}   # dark navy
HEADER_FG     = {"red": 1.0,   "green": 1.0,   "blue": 1.0}

ROW_ALT_BG    = {"red": 0.918, "green": 0.933, "blue": 0.965}   # light blue-gray
ROW_NORMAL_BG = {"red": 1.0,   "green": 1.0,   "blue": 1.0}

INCOME_FG     = {"red": 0.067, "green": 0.494, "blue": 0.165}   # forest green
EXPENSE_FG    = {"red": 0.741, "green": 0.149, "blue": 0.133}   # crimson
BALANCE_POS   = {"red": 0.067, "green": 0.494, "blue": 0.165}
BALANCE_NEG   = {"red": 0.741, "green": 0.149, "blue": 0.133}

DASH_BG       = {"red": 0.953, "green": 0.953, "blue": 0.953}   # light grey canvas
CARD_HDR_INC  = {"red": 0.067, "green": 0.494, "blue": 0.165}   # green card header
CARD_HDR_EXP  = {"red": 0.741, "green": 0.149, "blue": 0.133}   # red card header
CARD_HDR_NET  = {"red": 0.114, "green": 0.208, "blue": 0.380}   # navy card header
CARD_HDR_SAV  = {"red": 0.506, "green": 0.122, "blue": 0.584}   # purple card header
CARD_VAL_BG   = {"red": 1.0,   "green": 1.0,   "blue": 1.0}

MONTHLY_HDR   = {"red": 0.180, "green": 0.380, "blue": 0.255}   # deep green
MONTHLY_FG    = {"red": 1.0,   "green": 1.0,   "blue": 1.0}

_GOAL_HDR_BG  = {"red": 0.494, "green": 0.239, "blue": 0.659}
_GOAL_HDR_FG  = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
_GOAL_ROW_BG  = {"red": 0.965, "green": 0.941, "blue": 0.984}

# ── Module-level caches ───────────────────────────────────────────────────────
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
    creds_path     = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
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
    color = color or {"red": 0.75, "green": 0.75, "blue": 0.75}
    return {"style": style, "width": width, "color": color}


def _full_border(style="SOLID", width=1, color=None):
    side = _border_side(style, width, color)
    return {"top": side, "bottom": side, "left": side, "right": side}


def _cell_fmt(bg=None, fg=None, bold=False, h_align="LEFT",
              font_size=10, italic=False, v_align="MIDDLE",
              wrap="OVERFLOW_CELL", number_fmt=None):
    fmt = {
        "textFormat": {"bold": bold, "italic": italic, "fontSize": font_size},
        "horizontalAlignment": h_align,
        "verticalAlignment":   v_align,
        "wrapStrategy":        wrap,
    }
    if bg:
        fmt["backgroundColor"] = bg
    if fg:
        fmt["textFormat"]["foregroundColor"] = fg
    if number_fmt:
        fmt["numberFormat"] = number_fmt
    return fmt


def _col_width_req(sid, col, px):
    return {"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS",
                  "startIndex": col, "endIndex": col + 1},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}}


def _row_height_req(sid, start, end, px):
    return {"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS",
                  "startIndex": start, "endIndex": end},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}}


def _freeze_req(sid, rows=1, cols=0):
    return {"updateSheetProperties": {
        "properties": {"sheetId": sid,
                       "gridProperties": {"frozenRowCount": rows,
                                          "frozenColumnCount": cols}},
        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}}


def _repeat_cell(sid, r0, r1, c0, c1, fmt):
    return {"repeatCell": {
        "range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                  "startColumnIndex": c0, "endColumnIndex": c1},
        "cell": {"userEnteredFormat": fmt},
        "fields": "userEnteredFormat"}}


def _merge_req(sid, r0, r1, c0, c1):
    return {"mergeCells": {
        "range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                  "startColumnIndex": c0, "endColumnIndex": c1},
        "mergeType": "MERGE_ALL"}}


def _rupee(v: float) -> str:
    """Format float as ₹ X,XX,XXX.XX (Indian style)."""
    sign   = "-" if v < 0 else ""
    av     = abs(v)
    whole  = int(av)
    dec    = f"{av - whole:.2f}"[1:]   # ".XX"
    s      = str(whole)
    if len(s) <= 3:
        return f"{sign}₹{s}{dec}"
    last3  = s[-3:]
    rest   = s[:-3]
    parts  = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.insert(0, rest)
    return f"{sign}₹{','.join(parts)},{last3}{dec}"


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
        ws.clear()
        ws.insert_row(HEADERS, 1)
    _apply_txn_header_style(ws)
    _txn_sheet = ws
    return ws


def _apply_txn_header_style(ws):
    ss  = _connect()
    sid = ws.id
    col_pxs = [110, 120, 90, 140, 105, 230, 110, 110]  # +Balance col

    requests = [
        _freeze_req(sid, rows=1),
        _row_height_req(sid, 0, 1, 34),
        *[_col_width_req(sid, i, px) for i, px in enumerate(col_pxs)],
        _repeat_cell(sid, 0, 1, 0, len(HEADERS), {
            **_cell_fmt(bg=HEADER_BG, fg=HEADER_FG, bold=True,
                        h_align="CENTER", font_size=11),
            "borders": _full_border("SOLID", 2, {"red": 0.05, "green": 0.1, "blue": 0.3}),
        }),
        # Date and Timestamp → plain text
        *[_repeat_cell(sid, 1, 1000, c, c+1,
                       {"numberFormat": {"type": "TEXT"}})
          for c in (0, 1)],
        # Amount and Balance columns → number format
        _repeat_cell(sid, 1, 1000, 4, 5,
                     {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}}),
        _repeat_cell(sid, 1, 1000, 7, 8,
                     {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}}),
    ]
    ss.batch_update({"requests": requests})
    logger.info("Transaction sheet header styled")


def _style_new_row(ws, row_index: int, row_type: str, balance: float):
    ss  = _connect()
    sid = ws.id
    ri  = row_index - 1

    bg     = ROW_ALT_BG if row_index % 2 == 0 else ROW_NORMAL_BG
    amt_fg = INCOME_FG  if row_type == "income" else EXPENSE_FG
    bal_fg = BALANCE_POS if balance >= 0 else BALANCE_NEG

    requests = [
        # Full row background + borders
        _repeat_cell(sid, ri, ri+1, 0, len(HEADERS), {
            **_cell_fmt(bg=bg, font_size=10),
            "borders": _full_border(),
        }),
        # Amount (col 4) — colored + bold + right-aligned
        _repeat_cell(sid, ri, ri+1, 4, 5, {
            **_cell_fmt(bg=bg, fg=amt_fg, bold=True, h_align="RIGHT", font_size=10),
            "borders": _full_border(),
            "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
        }),
        # Balance (col 7) — colored + bold + right-aligned
        _repeat_cell(sid, ri, ri+1, 7, 8, {
            **_cell_fmt(bg=bg, fg=bal_fg, bold=True, h_align="RIGHT", font_size=10),
            "borders": _full_border(),
            "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
        }),
    ]
    ss.batch_update({"requests": requests})


def _compute_running_balance() -> float:
    """Return current running balance (all-time income − expense)."""
    ws = _get_txn_sheet()
    all_vals = ws.get_all_values()
    if len(all_vals) < 2:
        return 0.0
    header = [h.strip().lower() for h in all_vals[0]]
    try:
        i_type = header.index("type")
        i_amt  = header.index("amount")
        i_bal  = header.index("balance")
    except ValueError:
        return 0.0
    balance = 0.0
    for row in all_vals[1:]:
        if len(row) > i_amt:
            try:
                amt = float(str(row[i_amt]).replace(",", "") or 0)
            except (ValueError, TypeError):
                continue
            t = row[i_type].strip().lower() if len(row) > i_type else ""
            balance += amt if t == "income" else -amt
    return round(balance, 2)


def append_transaction(row: dict):
    """Append a transaction row, update running balance, refresh Dashboard & Monthly."""
    ws = _get_txn_sheet()
    now_ist = datetime.now(_IST)

    try:
        amount = float(str(row.get("amount", 0)).replace(",", "").strip())
    except (ValueError, TypeError):
        amount = 0.0

    row_type = row.get("type", "expense").strip().lower()

    # Compute new balance
    prev_balance = _compute_running_balance()
    new_balance  = round(prev_balance + (amount if row_type == "income" else -amount), 2)

    values = [
        row.get("date",      now_ist.strftime("%d-%m-%Y")),
        row.get("timestamp", now_ist.strftime("%I:%M:%S %p")),
        row_type,
        row.get("category", "Other").strip(),
        round(amount, 2),
        row.get("note", ""),
        row.get("user", ""),
        new_balance,
    ]

    ws.append_row(values, value_input_option="RAW")

    all_values  = ws.get_all_values()
    new_row_idx = len(all_values)
    _style_new_row(ws, new_row_idx, row_type, new_balance)

    # Refresh auxiliary sheets
    try:
        refresh_dashboard()
    except Exception as e:
        logger.warning(f"Dashboard refresh failed: {e}")
    try:
        refresh_monthly()
    except Exception as e:
        logger.warning(f"Monthly refresh failed: {e}")

    logger.info(f"Transaction appended: {values}")


def get_recent_transactions(user_id: str = None, limit: int = 10) -> list[dict]:
    ws         = _get_txn_sheet()
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return []
    header  = all_values[0]
    data    = all_values[1:]
    records = [dict(zip(header, r)) for r in data]
    return list(reversed(records))[:limit]


def get_summary(user_id: str = None) -> dict:
    ws        = _get_txn_sheet()
    all_vals  = ws.get_all_values()
    cur_month = datetime.now(_IST).strftime("%m-%Y")

    total_income = total_expense = 0.0
    by_category: dict = defaultdict(float)

    if len(all_vals) >= 2:
        header = [h.strip().lower() for h in all_vals[0]]
        try:
            i_date = header.index("date")
            i_type = header.index("type")
            i_cat  = header.index("category")
            i_amt  = header.index("amount")
        except ValueError:
            i_date, i_type, i_cat, i_amt = 0, 2, 3, 4

        for row in all_vals[1:]:
            if len(row) <= i_amt:
                continue
            if row[i_date].strip()[3:] != cur_month:
                continue
            try:
                amt = float(str(row[i_amt]).replace(",", "") or 0)
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
                amt = float(str(row[i_amt]).replace(",", "") or 0)
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

    top_cat     = max(month_cats, key=month_cats.get) if month_cats else "—"
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
# Dashboard sheet
# ─────────────────────────────────────────────────────────────────────────────

def refresh_dashboard():
    """
    Rebuild the Dashboard sheet with:
      • Row 1     : Title banner
      • Rows 3-6  : 4 KPI cards (Income / Expense / Net / Savings Rate) across cols A-H
      • Row 8     : Section header "Top Expense Categories (This Month)"
      • Rows 9-13 : Top-5 categories table
      • Row 15    : Section header "Recent Transactions"
      • Rows 16-20: Last 5 transactions
      • Row 22    : Last updated timestamp
    """
    ss = _connect()
    ws = _get_or_create("Dashboard", rows=50, cols=10)
    ws.clear()
    sid = ws.id

    bal    = get_balance()
    summ   = get_summary()
    recent = get_recent_transactions(limit=5)

    month_label   = summ["month"]
    total_income  = summ["total_income"]
    total_expense = summ["total_expense"]
    net           = summ["net"]
    savings_rate  = (net / total_income * 100) if total_income > 0 else 0.0
    net_balance   = bal["net_balance"]

    # ── Write cell values ─────────────────────────────────────────────────────
    # Row 1: Title
    ws.update("A1", [[f"💰 Finance Dashboard — {month_label}"]])

    # KPI cards: label in row 3, value in row 4-5 (merged), subtitle in row 6
    # Card 1: Income  (cols A-B)
    ws.update("A3", [["INCOME"],
                      [_rupee(total_income)],
                      [""],
                      ["This Month"]])
    # Card 2: Expense (cols C-D)
    ws.update("C3", [["EXPENSE"],
                      [_rupee(total_expense)],
                      [""],
                      ["This Month"]])
    # Card 3: Net Balance (cols E-F)
    ws.update("E3", [["NET BALANCE"],
                      [_rupee(net)],
                      [""],
                      ["This Month"]])
    # Card 4: Savings Rate (cols G-H)
    ws.update("G3", [["SAVINGS RATE"],
                      [f"{savings_rate:.1f}%"],
                      [""],
                      [f"All-time: {_rupee(net_balance)}"]])

    # Section: Top categories
    ws.update("A8",  [["📊 Top Expense Categories — " + month_label]])
    ws.update("A9",  [["Category", "", "Amount", "", "% of Expenses"]])
    cat_data = list(summ["by_category"].items())[:5]
    for i, (cat, amt) in enumerate(cat_data):
        pct = (amt / total_expense * 100) if total_expense > 0 else 0
        ws.update(f"A{10+i}", [[cat, "", _rupee(amt), "", f"{pct:.1f}%"]])
    # Fill empty rows if fewer than 5
    for i in range(len(cat_data), 5):
        ws.update(f"A{10+i}", [["—", "", "—", "", "—"]])

    # Section: Recent transactions
    ws.update("A15", [["🕐 Recent Transactions"]])
    ws.update("A16", [["Date", "Type", "Category", "Amount", "Note"]])
    for i, txn in enumerate(recent[:5]):
        amt = txn.get("Amount", "0")
        ws.update(f"A{17+i}", [[
            txn.get("Date", ""),
            txn.get("Type", "").upper(),
            txn.get("Category", ""),
            amt,
            txn.get("Note", ""),
        ]])
    for i in range(len(recent), 5):
        ws.update(f"A{17+i}", [["—", "—", "—", "—", "—"]])

    # Last updated
    now_str = datetime.now(_IST).strftime("%d %b %Y, %I:%M %p IST")
    ws.update("A22", [[f"Last updated: {now_str}"]])

    # ── Formatting requests ───────────────────────────────────────────────────
    WHITE = {"red": 1, "green": 1, "blue": 1}
    DARK  = {"red": 0.114, "green": 0.208, "blue": 0.380}

    req = [
        _freeze_req(sid, rows=0),
        # Canvas background
        _repeat_cell(sid, 0, 50, 0, 10, {"backgroundColor": DASH_BG}),
        # Title row
        _merge_req(sid, 0, 1, 0, 8),
        _repeat_cell(sid, 0, 1, 0, 8, {
            **_cell_fmt(bg=DARK, fg=WHITE, bold=True, h_align="CENTER",
                        font_size=16, v_align="MIDDLE"),
        }),
        _row_height_req(sid, 0, 1, 48),

        # Card header rows (row 3, index 2)
        _repeat_cell(sid, 2, 3, 0, 2,  {**_cell_fmt(bg=CARD_HDR_INC,  fg=WHITE, bold=True, h_align="CENTER", font_size=11), "borders": _full_border("SOLID", 2, CARD_HDR_INC)}),
        _repeat_cell(sid, 2, 3, 2, 4,  {**_cell_fmt(bg=CARD_HDR_EXP,  fg=WHITE, bold=True, h_align="CENTER", font_size=11), "borders": _full_border("SOLID", 2, CARD_HDR_EXP)}),
        _repeat_cell(sid, 2, 3, 4, 6,  {**_cell_fmt(bg=CARD_HDR_NET,  fg=WHITE, bold=True, h_align="CENTER", font_size=11), "borders": _full_border("SOLID", 2, CARD_HDR_NET)}),
        _repeat_cell(sid, 2, 3, 6, 8,  {**_cell_fmt(bg=CARD_HDR_SAV,  fg=WHITE, bold=True, h_align="CENTER", font_size=11), "borders": _full_border("SOLID", 2, CARD_HDR_SAV)}),

        # Card value rows (rows 4-5, indices 3-5)
        _merge_req(sid, 3, 5, 0, 2),
        _merge_req(sid, 3, 5, 2, 4),
        _merge_req(sid, 3, 5, 4, 6),
        _merge_req(sid, 3, 5, 6, 8),
        _repeat_cell(sid, 3, 5, 0, 2, {**_cell_fmt(bg=CARD_VAL_BG, fg=INCOME_FG,   bold=True, h_align="CENTER", font_size=20, v_align="MIDDLE"), "borders": _full_border("SOLID", 2, CARD_HDR_INC)}),
        _repeat_cell(sid, 3, 5, 2, 4, {**_cell_fmt(bg=CARD_VAL_BG, fg=EXPENSE_FG,  bold=True, h_align="CENTER", font_size=20, v_align="MIDDLE"), "borders": _full_border("SOLID", 2, CARD_HDR_EXP)}),
        _repeat_cell(sid, 3, 5, 4, 6, {**_cell_fmt(bg=CARD_VAL_BG, fg=CARD_HDR_NET,bold=True, h_align="CENTER", font_size=20, v_align="MIDDLE"), "borders": _full_border("SOLID", 2, CARD_HDR_NET)}),
        _repeat_cell(sid, 3, 5, 6, 8, {**_cell_fmt(bg=CARD_VAL_BG, fg=CARD_HDR_SAV,bold=True, h_align="CENTER", font_size=20, v_align="MIDDLE"), "borders": _full_border("SOLID", 2, CARD_HDR_SAV)}),
        _row_height_req(sid, 2, 3, 30),
        _row_height_req(sid, 3, 5, 42),

        # Card subtitle (row 6, index 5)
        _merge_req(sid, 5, 6, 0, 2),
        _merge_req(sid, 5, 6, 2, 4),
        _merge_req(sid, 5, 6, 4, 6),
        _merge_req(sid, 5, 6, 6, 8),
        _repeat_cell(sid, 5, 6, 0, 8, {
            **_cell_fmt(bg=DASH_BG, fg={"red": 0.5, "green": 0.5, "blue": 0.5},
                        italic=True, h_align="CENTER", font_size=9),
        }),
        _row_height_req(sid, 5, 6, 22),

        # Section headers (rows 8, 15)
        _merge_req(sid, 7, 8, 0, 8),
        _merge_req(sid, 14, 15, 0, 8),
        _repeat_cell(sid, 7, 8, 0, 8, {
            **_cell_fmt(bg=HEADER_BG, fg=WHITE, bold=True, h_align="LEFT", font_size=12),
        }),
        _repeat_cell(sid, 14, 15, 0, 8, {
            **_cell_fmt(bg=HEADER_BG, fg=WHITE, bold=True, h_align="LEFT", font_size=12),
        }),
        _row_height_req(sid, 7, 8, 30),
        _row_height_req(sid, 14, 15, 30),

        # Category table header (row 9)
        _repeat_cell(sid, 8, 9, 0, 5, {
            **_cell_fmt(bg={"red": 0.85, "green": 0.85, "blue": 0.85},
                        bold=True, h_align="CENTER", font_size=10),
            "borders": _full_border("SOLID", 1),
        }),
        # Category data rows (10-14)
        _repeat_cell(sid, 9, 14, 0, 5, {
            **_cell_fmt(bg=WHITE, font_size=10),
            "borders": _full_border(),
        }),
        _repeat_cell(sid, 9, 14, 2, 3, {
            **_cell_fmt(bg=WHITE, fg=EXPENSE_FG, bold=True, h_align="RIGHT", font_size=10),
        }),

        # Recent transactions header (row 16)
        _repeat_cell(sid, 15, 16, 0, 5, {
            **_cell_fmt(bg={"red": 0.85, "green": 0.85, "blue": 0.85},
                        bold=True, h_align="CENTER", font_size=10),
            "borders": _full_border("SOLID", 1),
        }),
        # Recent transactions data (rows 17-21)
        _repeat_cell(sid, 16, 21, 0, 5, {
            **_cell_fmt(bg=WHITE, font_size=10),
            "borders": _full_border(),
        }),
        _repeat_cell(sid, 16, 21, 3, 4, {
            **_cell_fmt(bg=WHITE, bold=True, h_align="RIGHT", font_size=10),
        }),

        # Last updated (row 22)
        _repeat_cell(sid, 21, 22, 0, 8, {
            **_cell_fmt(bg=DASH_BG,
                        fg={"red": 0.5, "green": 0.5, "blue": 0.5},
                        italic=True, h_align="RIGHT", font_size=9),
        }),

        # Column widths
        _col_width_req(sid, 0, 140),
        _col_width_req(sid, 1, 10),
        _col_width_req(sid, 2, 130),
        _col_width_req(sid, 3, 10),
        _col_width_req(sid, 4, 130),
        _col_width_req(sid, 5, 10),
        _col_width_req(sid, 6, 130),
        _col_width_req(sid, 7, 10),
        _col_width_req(sid, 8, 180),
    ]

    ss.batch_update({"requests": req})
    logger.info("Dashboard refreshed")


# ─────────────────────────────────────────────────────────────────────────────
# Monthly Summary sheet
# ─────────────────────────────────────────────────────────────────────────────

MONTHLY_HEADERS = ["Month", "Income (₹)", "Expense (₹)", "Net (₹)", "Savings Rate"]


def refresh_monthly():
    """
    Rebuild the Monthly sheet with one row per calendar month found in Transactions.
    Rows sorted oldest → newest.
    """
    ss = _connect()
    ws = _get_or_create("Monthly", rows=100, cols=6)
    ws.clear()
    sid = ws.id

    # Aggregate by month
    txn_ws    = _get_txn_sheet()
    all_vals  = txn_ws.get_all_values()
    monthly: dict = defaultdict(lambda: {"income": 0.0, "expense": 0.0})

    if len(all_vals) >= 2:
        header = [h.strip().lower() for h in all_vals[0]]
        try:
            i_date = header.index("date")
            i_type = header.index("type")
            i_amt  = header.index("amount")
        except ValueError:
            i_date, i_type, i_amt = 0, 2, 4

        for row in all_vals[1:]:
            if len(row) <= i_amt:
                continue
            date_str = row[i_date].strip()
            if len(date_str) < 7:
                continue
            try:
                dt  = datetime.strptime(date_str, "%d-%m-%Y")
                key = dt.strftime("%m-%Y")
                lbl = dt.strftime("%b %Y")
            except ValueError:
                continue
            try:
                amt = float(str(row[i_amt]).replace(",", "") or 0)
            except (ValueError, TypeError):
                continue
            t = row[i_type].strip().lower()
            monthly[key]["label"] = lbl
            if t == "income":
                monthly[key]["income"] += amt
            else:
                monthly[key]["expense"] += amt

    # Sort by month key (MM-YYYY)
    sorted_keys = sorted(monthly.keys(),
                         key=lambda k: datetime.strptime(k, "%m-%Y"))

    # Write header
    ws.update("A1", [MONTHLY_HEADERS])

    rows_to_write = []
    for k in sorted_keys:
        m  = monthly[k]
        inc = round(m["income"],  2)
        exp = round(m["expense"], 2)
        net = round(inc - exp,    2)
        sr  = round(net / inc * 100, 1) if inc > 0 else 0.0
        rows_to_write.append([m.get("label", k), inc, exp, net, f"{sr}%"])

    if rows_to_write:
        ws.update(f"A2", rows_to_write, value_input_option="RAW")

    n = len(rows_to_write)

    # ── Formatting ────────────────────────────────────────────────────────────
    WHITE = {"red": 1, "green": 1, "blue": 1}
    req = [
        _freeze_req(sid, rows=1),
        _row_height_req(sid, 0, 1, 32),
        # Header
        _repeat_cell(sid, 0, 1, 0, 5, {
            **_cell_fmt(bg=MONTHLY_HDR, fg=MONTHLY_FG, bold=True,
                        h_align="CENTER", font_size=11),
            "borders": _full_border("SOLID", 2, {"red": 0.1, "green": 0.25, "blue": 0.15}),
        }),
        # Data rows
        _col_width_req(sid, 0, 110),
        _col_width_req(sid, 1, 130),
        _col_width_req(sid, 2, 130),
        _col_width_req(sid, 3, 130),
        _col_width_req(sid, 4, 110),
    ]

    for i in range(n):
        row_i  = i + 1   # 0-based
        alt_bg = ROW_ALT_BG if i % 2 == 0 else ROW_NORMAL_BG
        req += [
            _repeat_cell(sid, row_i, row_i+1, 0, 5, {
                **_cell_fmt(bg=alt_bg, font_size=10),
                "borders": _full_border(),
            }),
            # Income green
            _repeat_cell(sid, row_i, row_i+1, 1, 2, {
                **_cell_fmt(bg=alt_bg, fg=INCOME_FG, bold=True, h_align="RIGHT"),
                "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
            }),
            # Expense red
            _repeat_cell(sid, row_i, row_i+1, 2, 3, {
                **_cell_fmt(bg=alt_bg, fg=EXPENSE_FG, bold=True, h_align="RIGHT"),
                "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
            }),
            # Net — colour by sign
            _repeat_cell(sid, row_i, row_i+1, 3, 4, {
                **_cell_fmt(bg=alt_bg,
                             fg=INCOME_FG if rows_to_write[i][3] >= 0 else EXPENSE_FG,
                             bold=True, h_align="RIGHT"),
                "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
            }),
        ]

    if req:
        ss.batch_update({"requests": req})
    logger.info(f"Monthly sheet refreshed ({n} months)")


# ─────────────────────────────────────────────────────────────────────────────
# Goals sheet
# ─────────────────────────────────────────────────────────────────────────────

GOAL_HEADERS = ["Name", "Target", "Saved", "Deadline", "Created", "Status"]


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
    ss  = _connect()
    sid = ws.id
    req = [
        _freeze_req(sid, rows=1),
        _col_width_req(sid, 0, 180),
        _col_width_req(sid, 1, 110),
        _col_width_req(sid, 2, 110),
        _col_width_req(sid, 3, 120),
        _col_width_req(sid, 4, 120),
        _col_width_req(sid, 5, 100),
        _row_height_req(sid, 0, 1, 32),
        _repeat_cell(sid, 0, 1, 0, len(GOAL_HEADERS), {
            **_cell_fmt(bg=_GOAL_HDR_BG, fg=_GOAL_HDR_FG, bold=True,
                        h_align="CENTER", font_size=11),
            "borders": _full_border("SOLID", 2, {"red": 0.3, "green": 0.1, "blue": 0.5}),
        }),
    ]
    ss.batch_update({"requests": req})
    logger.info("Goal sheet header styled")


def _style_goal_data_row(ws):
    ss  = _connect()
    sid = ws.id
    req = [_repeat_cell(sid, 1, 2, 0, len(GOAL_HEADERS), {
        **_cell_fmt(bg=_GOAL_ROW_BG, font_size=10),
        "borders": _full_border(),
    })]
    ss.batch_update({"requests": req})


# ─────────────────────────────────────────────────────────────────────────────
# Public Goal API
# ─────────────────────────────────────────────────────────────────────────────

def get_goal() -> dict | None:
    ws   = _get_goal_sheet()
    rows = ws.get_all_values()
    if len(rows) < 2 or not any(rows[1]):
        return None
    goal = dict(zip(GOAL_HEADERS, rows[1]))
    if goal.get("Status", "").strip().lower() != "active":
        return None
    return goal


def create_goal(name: str, target: float, deadline: str = "") -> dict:
    global _goal_sheet
    ws      = _get_goal_sheet()
    now_ist = datetime.now(_IST).strftime("%d-%m-%Y")
    row = [name.strip(), round(target, 2), 0.0,
           deadline.strip(), now_ist, "active"]
    all_rows = ws.get_all_values()
    if len(all_rows) >= 2:
        ws.update("A2", [row], value_input_option="RAW")
    else:
        ws.append_row(row, value_input_option="RAW")
    _goal_sheet = None
    _style_goal_data_row(_get_goal_sheet())
    return get_goal()


def add_to_goal(amount: float, username: str = "goal") -> tuple[dict | None, bool]:
    global _goal_sheet
    ws   = _get_goal_sheet()
    rows = ws.get_all_values()
    if len(rows) < 2 or not any(rows[1]):
        return None, False
    goal   = dict(zip(GOAL_HEADERS, rows[1]))
    status = goal.get("Status", "").strip().lower()
    if status not in ("active", "completed"):
        return None, False

    goal_name  = goal.get("Name", "Goal")
    prev_saved = float(goal.get("Saved", 0))
    target     = float(goal.get("Target", 0))

    if status == "completed" or prev_saved >= target:
        return None, False

    remaining = round(target - prev_saved, 2)
    deposit   = round(min(amount, remaining), 2)
    new_saved = round(prev_saved + deposit, 2)

    ws.update("C2", [[new_saved]], value_input_option="RAW")

    just_completed = new_saved >= target
    if just_completed:
        ws.update("F2", [["completed"]], value_input_option="RAW")

    _goal_sheet = None
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

    if just_completed:
        income_row = {
            "date":      now_ist.strftime("%d-%m-%Y"),
            "timestamp": now_ist.strftime("%I:%M:%S %p"),
            "type":      "income",
            "category":  "Goal Achieved",
            "amount":    new_saved,
            "note":      f"Goal completed: {goal_name}",
            "user":      username,
        }
        append_transaction(income_row)

    goal["Saved"]  = str(new_saved)
    goal["Status"] = "completed" if just_completed else "active"
    return goal, just_completed


def delete_goal(username: str = "goal") -> bool:
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
