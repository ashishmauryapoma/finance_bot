"""
goals_sheets.py — Google Sheets handler for Savings Goals
Sheet name: "Goals"
Columns: ID | Name | Target | Saved | Deadline | Created | User | Status
"""

import os
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_IST   = timezone(timedelta(hours=5, minutes=30))
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

GOALS_HEADERS = ["ID", "Name", "Target", "Saved", "Deadline", "Created", "User", "Status"]

# ── Colour palette (matches sheets_handler style) ────────────────────────────
_HEADER_BG   = {"red": 0.157, "green": 0.306, "blue": 0.612}
_HEADER_FG   = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
_DONE_BG     = {"red": 0.204, "green": 0.659, "blue": 0.325}
_DONE_FG     = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
_ALT_BG      = {"red": 0.906, "green": 0.925, "blue": 0.969}
_WHITE       = {"red": 1.0,   "green": 1.0,   "blue": 1.0}

_client      = None
_spreadsheet = None
_goals_ws    = None


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


def _get_goals_sheet():
    global _goals_ws
    if _goals_ws:
        return _goals_ws
    ss = _connect()
    try:
        ws = ss.worksheet("Goals")
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title="Goals", rows=500, cols=len(GOALS_HEADERS))
    existing = ws.row_values(1)
    if existing != GOALS_HEADERS:
        ws.insert_row(GOALS_HEADERS, 1)
        _style_goals_header(ws)
    _goals_ws = ws
    return ws


def _style_goals_header(ws):
    ss  = _connect()
    sid = ws.id
    col_pxs = [160, 200, 110, 110, 110, 110, 110, 100]
    requests = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sid,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        }
    ]
    for i, px in enumerate(col_pxs):
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS",
                          "startIndex": i, "endIndex": i + 1},
                "properties": {"pixelSize": px},
                "fields": "pixelSize",
            }
        })
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": len(GOALS_HEADERS)},
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": _HEADER_BG,
                    "textFormat": {"bold": True, "fontSize": 11,
                                   "foregroundColor": _HEADER_FG},
                    "horizontalAlignment": "CENTER",
                }
            },
            "fields": "userEnteredFormat",
        }
    })
    ss.batch_update({"requests": requests})


def _style_goal_row(ws, row_index: int, status: str):
    """Colour a newly written goal row (alternating bg; green if completed)."""
    ss  = _connect()
    sid = ws.id
    ri  = row_index - 1   # 0-based

    if status == "completed":
        bg = _DONE_BG
    else:
        bg = _ALT_BG if row_index % 2 == 0 else _WHITE

    ss.batch_update({"requests": [{
        "repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": ri, "endRowIndex": ri + 1,
                      "startColumnIndex": 0, "endColumnIndex": len(GOALS_HEADERS)},
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": bg,
                    "textFormat": {"fontSize": 10},
                }
            },
            "fields": "userEnteredFormat",
        }
    }]})


def _ist_now() -> datetime:
    return datetime.now(tz=_IST)


def _all_rows() -> list[dict]:
    ws   = _get_goals_sheet()
    data = ws.get_all_values()
    if len(data) < 2:
        return []
    header = data[0]
    return [dict(zip(header, row)) for row in data[1:] if any(row)]


def _find_row_index(goal_id: str) -> Optional[int]:
    """Return 1-based sheet row index for a goal, or None."""
    ws   = _get_goals_sheet()
    data = ws.get_all_values()
    for i, row in enumerate(data[1:], start=2):
        if row and row[0] == goal_id:
            return i
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def create_goal(name: str, target: float, deadline: str, username: str) -> dict:
    """
    Insert a new goal row.
    deadline: 'DD-MM-YYYY' string.
    Returns the goal dict.
    """
    ws      = _get_goals_sheet()
    goal_id = str(uuid.uuid4())[:8].upper()
    now     = _ist_now().strftime("%d-%m-%Y")
    row     = [goal_id, name, round(target, 2), 0.0, deadline, now, username, "active"]
    ws.append_row(row, value_input_option="RAW")

    all_vals = ws.get_all_values()
    _style_goal_row(ws, len(all_vals), "active")
    logger.info(f"Goal created: {goal_id} — {name}")
    return dict(zip(GOALS_HEADERS, row))


def deposit_to_goal(goal_id: str, amount: float) -> dict:
    """
    Add `amount` to goal's Saved column.
    Returns updated goal dict.
    Raises ValueError if goal not found or already completed/cancelled.
    """
    ws       = _get_goals_sheet()
    row_idx  = _find_row_index(goal_id)
    if not row_idx:
        raise ValueError(f"Goal '{goal_id}' not found.")

    row_data = ws.row_values(row_idx)
    goal     = dict(zip(GOALS_HEADERS, row_data))

    if goal["Status"] in ("completed", "cancelled"):
        raise ValueError(f"Goal is already {goal['Status']}.")

    new_saved  = round(float(goal["Saved"]) + amount, 2)
    target     = float(goal["Target"])
    new_status = "completed" if new_saved >= target else "active"

    # Update Saved (col 4) and Status (col 8) — 1-based column index
    saved_cell  = gspread.utils.rowcol_to_a1(row_idx, 4)
    status_cell = gspread.utils.rowcol_to_a1(row_idx, 8)
    ws.update(saved_cell,  [[new_saved]],    value_input_option="RAW")
    ws.update(status_cell, [[new_status]], value_input_option="RAW")

    _style_goal_row(ws, row_idx, new_status)

    goal["Saved"]  = new_saved
    goal["Status"] = new_status
    logger.info(f"Deposit ₹{amount} → goal {goal_id}; saved={new_saved}, status={new_status}")
    return goal


def get_goals(username: str = None, include_done: bool = False) -> list[dict]:
    """
    Return list of goals for a user.
    If include_done=False, only active goals are returned.
    """
    rows = _all_rows()
    if username:
        rows = [r for r in rows if r.get("User") == username]
    if not include_done:
        rows = [r for r in rows if r.get("Status") == "active"]
    return rows


def delete_goal(goal_id: str) -> bool:
    """Mark a goal as cancelled (soft delete). Returns True if found."""
    ws      = _get_goals_sheet()
    row_idx = _find_row_index(goal_id)
    if not row_idx:
        return False
    status_cell = gspread.utils.rowcol_to_a1(row_idx, 8)
    ws.update(status_cell, [["cancelled"]], value_input_option="RAW")
    _style_goal_row(ws, row_idx, "cancelled")
    return True


def get_goal_by_id(goal_id: str) -> Optional[dict]:
    for r in _all_rows():
        if r.get("ID") == goal_id:
            return r
    return None
