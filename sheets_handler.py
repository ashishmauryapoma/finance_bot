"""
Google Sheets handler — read and write financial transactions
- Transactions sheet: styled table with bold headers, alternating row colors, borders
- Summary sheet: auto-updated summary table with totals by category
"""

import os
import logging
from datetime import datetime
from collections import defaultdict

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

HEADERS = ["Date", "Type", "Category", "Amount", "Note", "User", "Timestamp"]

# ── Styling constants ─────────────────────────────────────────────────────────
HEADER_BG        = {"red": 0.157, "green": 0.306, "blue": 0.612}   # deep blue
HEADER_FG        = {"red": 1.0,   "green": 1.0,   "blue": 1.0}     # white
ROW_ALT_BG       = {"red": 0.906, "green": 0.925, "blue": 0.969}   # light blue-gray
ROW_NORMAL_BG    = {"red": 1.0,   "green": 1.0,   "blue": 1.0}     # white
INCOME_FG        = {"red": 0.106, "green": 0.533, "blue": 0.196}   # green
EXPENSE_FG       = {"red": 0.741, "green": 0.149, "blue": 0.133}   # red
SUMMARY_HDR_BG   = {"red": 0.204, "green": 0.659, "blue": 0.325}   # green
SUMMARY_HDR_FG   = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
TOTAL_BG         = {"red": 0.988, "green": 0.914, "blue": 0.698}   # soft yellow

_client      = None
_spreadsheet = None
_txn_sheet   = None
_sum_sheet   = None


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
    """Bold colored header row + freeze + column widths."""
    ss      = _connect()
    sid     = ws.id
    col_pxs = [110, 90, 140, 100, 220, 110, 160]   # per column

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

    # Amount column (index 3) gets colored text
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": ri, "endRowIndex": ri + 1,
                      "startColumnIndex": 3, "endColumnIndex": 4},
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
# Summary sheet
# ─────────────────────────────────────────────────────────────────────────────

def _get_sum_sheet():
    global _sum_sheet
    if _sum_sheet:
        return _sum_sheet
    _sum_sheet = _get_or_create("Summary", rows=100, cols=10)
    return _sum_sheet


def _rebuild_summary_sheet():
    """
    Wipe the Summary sheet and rewrite a fully styled summary table
    for the current month based on all transactions.
    """
    ws  = _get_sum_sheet()
    ss  = _connect()
    sid = ws.id

    # ── Gather data ──────────────────────────────────────────────────────────
    txn_ws      = _get_txn_sheet()
    all_rows    = txn_ws.get_all_records()
    cur_month   = datetime.now().strftime("%Y-%m")
    month_label = datetime.now().strftime("%B %Y")

    total_income  = 0.0
    total_expense = 0.0
    by_category   = defaultdict(float)
    income_cats   = defaultdict(float)

    for row in all_rows:
        if not str(row.get("Date", "")).startswith(cur_month):
            continue
        try:
            amt = float(row.get("Amount", 0))
        except (ValueError, TypeError):
            continue
        t   = str(row.get("Type", "")).lower()
        cat = str(row.get("Category", "Other"))
        if t == "income":
            total_income += amt
            income_cats[cat] += amt
        else:
            total_expense += amt
            by_category[cat] += amt

    net = total_income - total_expense

    # ── Build cell data ──────────────────────────────────────────────────────
    data = []

    # Title
    data.append([f"📊 Finance Summary — {month_label}", "", ""])

    # Spacer
    data.append(["", "", ""])

    # ── Expenses table ───────────────────────────────────────────────────────
    data.append(["💸 EXPENSES BY CATEGORY", "", ""])
    data.append(["Category", "Amount (₹)", "% of Total"])

    exp_start_row = len(data) + 1   # 1-based
    for cat, amt in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
        pct = f"{(amt / total_expense * 100):.1f}%" if total_expense else "0%"
        data.append([cat, amt, pct])

    data.append(["TOTAL EXPENSES", total_expense, "100%"])
    exp_end_row = len(data)

    # Spacer
    data.append(["", "", ""])

    # ── Income table ─────────────────────────────────────────────────────────
    data.append(["📥 INCOME BY CATEGORY", "", ""])
    data.append(["Category", "Amount (₹)", "% of Total"])

    inc_start_row = len(data) + 1
    for cat, amt in sorted(income_cats.items(), key=lambda x: x[1], reverse=True):
        pct = f"{(amt / total_income * 100):.1f}%" if total_income else "0%"
        data.append([cat, amt, pct])

    data.append(["TOTAL INCOME", total_income, "100%"])
    inc_end_row = len(data)

    # Spacer
    data.append(["", "", ""])

    # ── Net summary ──────────────────────────────────────────────────────────
    data.append(["💰 NET SUMMARY", "", ""])
    data.append(["Total Income",  total_income,  ""])
    data.append(["Total Expense", total_expense, ""])
    net_row = len(data) + 1
    data.append(["Net Balance",   net,            "Surplus" if net >= 0 else "Deficit"])

    # ── Write to sheet ───────────────────────────────────────────────────────
    ws.clear()
    ws.update("A1", data, value_input_option="USER_ENTERED")

    # ── Batch format ─────────────────────────────────────────────────────────
    total_rows = len(data)
    requests   = []

    # Column widths
    requests += [
        _col_width_request(sid, 0, 200),
        _col_width_request(sid, 1, 140),
        _col_width_request(sid, 2, 110),
    ]

    def _rng(r1, r2, c1, c2):
        return {"sheetId": sid, "startRowIndex": r1 - 1, "endRowIndex": r2,
                "startColumnIndex": c1, "endColumnIndex": c2}

    def _fmt_req(r1, r2, c1, c2, **kw):
        return {
            "repeatCell": {
                "range": _rng(r1, r2, c1, c2),
                "cell": {"userEnteredFormat": {
                    **_cell_fmt(**kw),
                    "borders": _full_border(),
                }},
                "fields": "userEnteredFormat",
            }
        }

    # Title row
    requests.append({
        "mergeCells": {
            "range": _rng(1, 1, 0, 3),
            "mergeType": "MERGE_ALL",
        }
    })
    requests.append(_fmt_req(1, 1, 0, 3,
                             bg=HEADER_BG, fg=HEADER_FG,
                             bold=True, h_align="CENTER", font_size=13))
    requests.append(_row_height_request(sid, 0, 1, 38))

    # Section headers (Expenses / Income / Net)
    for label_row in [3, len(by_category) + 6, len(by_category) + len(income_cats) + 10]:
        if label_row <= total_rows:
            requests.append({
                "mergeCells": {
                    "range": _rng(label_row, label_row, 0, 3),
                    "mergeType": "MERGE_ALL",
                }
            })
            requests.append(_fmt_req(label_row, label_row, 0, 3,
                                     bg=SUMMARY_HDR_BG, fg=SUMMARY_HDR_FG,
                                     bold=True, h_align="LEFT", font_size=11))

    # Table column headers (Category / Amount / %)
    for hdr_row in [4, len(by_category) + 7]:
        if hdr_row <= total_rows:
            requests.append(_fmt_req(hdr_row, hdr_row, 0, 3,
                                     bg={"red": 0.85, "green": 0.92, "blue": 0.83},
                                     bold=True, h_align="CENTER"))

    # TOTAL rows — yellow background, bold
    for tot_row in [exp_end_row, inc_end_row, net_row]:
        if tot_row <= total_rows:
            requests.append(_fmt_req(tot_row, tot_row, 0, 3,
                                     bg=TOTAL_BG, bold=True, h_align="LEFT"))

    # Amount column right-align for all data rows
    requests.append({
        "repeatCell": {
            "range": _rng(1, total_rows, 1, 2),
            "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT"}},
            "fields": "userEnteredFormat.horizontalAlignment",
        }
    })

    # Freeze title row
    requests.append(_freeze_request(sid, rows=1))

    ss.batch_update({"requests": requests})
    logger.info("Summary sheet rebuilt and styled")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def append_transaction(row: dict):
    """Append a transaction row, style it, then refresh the Summary sheet."""
    ws = _get_txn_sheet()

    values = [
        row.get("date", ""),
        row.get("type", "expense"),
        row.get("category", "Other"),
        row.get("amount", 0),
        row.get("note", ""),
        row.get("user", ""),
        row.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]

    ws.append_row(values, value_input_option="USER_ENTERED")

    # Style the new row
    all_values  = ws.get_all_values()
    new_row_idx = len(all_values)          # 1-based
    _style_new_row(ws, new_row_idx, row.get("type", "expense"))

    # Rebuild summary
    try:
        _rebuild_summary_sheet()
    except Exception as e:
        logger.warning(f"Summary rebuild failed (non-fatal): {e}")

    logger.info(f"Transaction appended: {values}")


def get_recent_transactions(user_id: str = None, limit: int = 10) -> list[dict]:
    ws       = _get_txn_sheet()
    all_rows = list(reversed(ws.get_all_records()))
    return all_rows[:limit] if all_rows else []


def get_summary(user_id: str = None) -> dict:
    ws          = _get_txn_sheet()
    all_rows    = ws.get_all_records()
    cur_month   = datetime.now().strftime("%Y-%m")

    total_income = total_expense = 0.0
    by_category  = defaultdict(float)

    for row in all_rows:
        if not str(row.get("Date", "")).startswith(cur_month):
            continue
        try:
            amt = float(row.get("Amount", 0))
        except (ValueError, TypeError):
            continue
        t   = str(row.get("Type", "")).lower()
        cat = str(row.get("Category", "Other"))
        if t == "income":
            total_income += amt
        else:
            total_expense += amt
            by_category[cat] += amt

    return {
        "month":         datetime.now().strftime("%B %Y"),
        "total_income":  total_income,
        "total_expense": total_expense,
        "net":           total_income - total_expense,
        "by_category":   dict(sorted(by_category.items(),
                                     key=lambda x: x[1], reverse=True)),
    }
