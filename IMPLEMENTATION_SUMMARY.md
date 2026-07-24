# Multiple Goals Support Implementation Summary

## Overview
Updated the Telegram Finance Bot to support multiple concurrent savings goals instead of a single goal. The implementation focuses on:

1. **Multiple Goals Management**: Users can create, manage, and track multiple goals simultaneously
2. **Completed Goals Locking**: When goals complete, funds remain locked until explicitly broken
3. **Enhanced Balance Display**: Shows goal breakdown and total locked amount
4. **Natural Language Detection**: Auto-detects goal deposits with interactive selection
5. **No Auto-Booking on Completion**: Removed the auto-income booking behavior

---

## File Changes

### 1. **sheets_handler.py** - Data Model & CRUD Operations

#### New Data Structure
```python
GOAL_HEADERS = ["Name", "Target", "Saved", "Deadline", "Created", "Status", "LastModified"]
```

**Status values**: `active`, `completed`, `deleted`

#### New Functions

| Function | Purpose |
|----------|---------|
| `get_all_goals(status_filter=None)` | Get all goals, optionally filtered by status |
| `get_goal_by_name(name: str)` | Get specific goal by name |
| `get_active_goals()` | Get all active goals |
| `get_completed_goals()` | Get all completed goals |
| `create_goal(name, target, deadline)` | Create new goal (no replacement) |
| `add_to_goal(goal_name, amount, username)` | Add to specific goal |
| `break_goal(goal_name, username)` | Break/delete goal, refund amount |

#### Behavior Changes
- **`create_goal()`**: Now appends new goals instead of replacing. Checks for duplicate names.
- **`add_to_goal()`**: Takes `goal_name` parameter instead of working with single active goal. Returns `(goal, just_completed)`.
  - On completion: Sets status to `completed`, does NOT auto-book income
  - Still logs deposit as "Goal Saving" transaction
- **`break_goal()`**: Marks goal as "deleted" (keeps history). Refunds saved amount as "Goal Refund" income if > 0.

#### Sheet Structure
- Multiple rows now support many goals
- Headers include `LastModified` for tracking changes
- Status column tracks goal lifecycle: active → completed → deleted

---

### 2. **goal_handler.py** - Formatting & Display

#### New Functions

| Function | Purpose |
|----------|---------|
| `format_goal_complete(goal)` | Celebrates goal completion (no income note) |
| `format_goals_list(active_goals, completed_goals)` | Shows all goals with summaries |
| `format_goal_details(goal)` | Detailed view of single goal |

#### Updated Functions
- **`format_goal_card()`**: Remains same, formats individual goal progress card

#### Message Enhancements
- Goals list shows totals for active and locked amounts
- Goal details show refund option if completed
- Progress bars display percentage and remaining amount

---

### 3. **groq_handler.py** - NLP Goal Detection

#### Updated Function
```python
async def detect_goal_deposit(text: str) -> dict | None
```

**Returns**:
```python
{
    "is_goal_deposit": bool,
    "amount": float or None,
    "goal_hint": str or None  # NEW: keyword/name hint
}
```

#### Enhancement
- Now extracts goal name hint from user message
- Enables smart goal matching when multiple goals exist
- Example: "saved 500 for trip" → `goal_hint="trip"`

---

### 4. **bot.py** - Command Handlers & Message Processing

#### Updated Imports
```python
from sheets_handler import (
    get_all_goals, get_goal_by_name, get_active_goals, get_completed_goals,
    create_goal, add_to_goal, break_goal  # Updated function signatures
)
from goal_handler import (
    format_goal_card, format_goal_complete, 
    format_goals_list, format_goal_details  # New functions
)
```

#### Message Handler (`handle_message`)
- Checks for goal deposit across ALL active goals
- If multiple goals exist without a hint match:
  - Shows inline buttons for goal selection
  - Stores pending deposit in `user_data`
- If single goal or hint matches one goal:
  - Auto-deposits to matching goal
- No auto-booking on completion

#### Balance Command (`/balance`)
- **Before**: Showed only net balance
- **After**: Shows:
  - Net balance (all transactions, excluding goal savings)
  - This month income/expense breakdown
  - Active goals list with progress
  - Completed goals list (locked amounts)
  - Total locked in completed goals

#### New Goal Commands

| Command | Behavior |
|---------|----------|
| `/goal` (no args) | Show all goals (active + completed) |
| `/goal list` | Alias for show all |
| `/goal set <name> \| <amount> \| <deadline>` | Create new goal (duplicate name check) |
| `/goal view <name>` | View detailed goal info |
| `/goal add <name> <amount>` | Add to specific goal (by name) |
| `/goal break <name>` | Break goal with confirmation |

#### Goal Status Handler (`_goal_status`)
- Shows `format_goals_list()` with active + completed breakdown
- Displays total saved active and total locked completed

#### New Callback Handler
- **`goal_deposit:<name>`**: Handle inline goal selection
- **`goal_break:<name>\|yes/no`**: Confirmation for breaking goals

#### Help Command
Updated to reflect new commands:
- `/goal set <name> | <amount> | <deadline>` — Create goal
- `/goal view <name>` — View specific goal
- `/goal add <name> <amount>` — Add savings to goal
- `/goal break <name>` — Delete goal & refund balance

---

## Key Behavior Changes

### ✅ Goal Completion
| Aspect | Before | After |
|--------|--------|-------|
| Storage | Single goal slot | Multiple rows |
| Completion | Auto-books as income | Locks in goal (status=completed) |
| Auto-booking | Yes | No |
| Refund logic | On delete only | On break, returns to net balance |

### ✅ Natural Language Detection
| Aspect | Before | After |
|--------|--------|-------|
| Multi-goal support | N/A (single goal) | Interactive selection with buttons |
| Goal hint extraction | No | Yes (keyword matching) |
| Auto-match | N/A | If single goal or hint matches |

### ✅ Balance Display
| Aspect | Before | After |
|--------|--------|-------|
| Shows | Net balance only | Net balance + goals breakdown |
| Goal visibility | N/A (single only) | All active + completed listed |
| Locked amount | N/A | Total locked in completed goals shown |

---

## Data Flow Examples

### Example 1: Creating Multiple Goals
```
User: /goal set Goa Trip | 50000 | 2026-12-01
Bot: ✅ Goal created!

User: /goal set Car Fund | 200000 | 2026-06-01
Bot: ✅ Goal created!

User: /goal
Bot: Shows both active goals with progress
```

### Example 2: Multiple Goal Deposit (Auto-Selection)
```
User: saved 2000 for trip
Bot: Which goal should I add ₹2000 to?
     [💰 Goa Trip] [💰 Car Fund]
User: [Taps "Goa Trip"]
Bot: ✅ ₹2000 added to Goa Trip
```

### Example 3: Goal Completion & Locking
```
User: /goal add "Goa Trip" 10000  (completes goal)
Bot: 🏆 Goal Complete!
     Funds locked in goal until you break it.

User: /balance
Bot: Shows ✨ Completed Goals: 🔒 Goa Trip — ₹50,000 (locked)

User: /goal break "Goa Trip"
Bot: 🗑️ Goal deleted.
     💰 ₹50,000 refunded to your balance.
```

---

## Migration Notes

### If Upgrading from Single-Goal System
1. **Existing single goal will be preserved** with status=`active`
2. Completed goal status becomes `completed` (funds locked)
3. New goals can be created alongside existing one
4. `/goal add <name> <amount>` requires goal name (unlike old `/goal add <amount>`)

### Breaking Changes
- **`get_goal()`**: REMOVED. Use `get_active_goals()` instead
- **`create_goal()` signature**: Now creates new row, doesn't replace
- **`add_to_goal()` signature**: Takes `goal_name` as first parameter
- **`delete_goal()`**: REMOVED. Use `break_goal()` instead
- **`/goal add <amount>`**: Changed to `/goal add <name> <amount>`
- **`/goal delete`**: Changed to `/goal break <name>`
- **Goal completion**: No longer auto-books income

---

## Testing Checklist

- [ ] Create multiple goals without conflicts
- [ ] Add to specific goal by name
- [ ] View goal details with `/goal view <name>`
- [ ] Goal completion locks funds (no income booking)
- [ ] `/balance` shows active + completed breakdown
- [ ] Break goal refunds amount correctly
- [ ] Natural language detection with multiple goals shows button selection
- [ ] Goal hint matching works ("saved 500 for goa" → suggests "Goa Trip")
- [ ] Single active goal auto-deposits without selection
- [ ] Duplicate goal names are rejected

---

## Future Enhancements (Not Implemented)
- Goal editing after creation (update target/deadline)
- Goal analytics (spending per goal over time)
- Goal sharing/collaboration
- Recurring goals (monthly, annual)
- Goal categories and grouping
