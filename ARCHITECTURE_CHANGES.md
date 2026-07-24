# Architecture Changes: Single Goal → Multiple Goals

## Data Model

### Before (Single Goal)
```
Goals Sheet (Single Row Model):
┌───────────────┬────────┬───────┬──────────┬─────────┬────────┐
│ Name          │ Target │ Saved │ Deadline │ Created │ Status │
├───────────────┼────────┼───────┼──────────┼─────────┼────────┤
│ Goa Trip      │ 50000  │ 25000 │ 2026-01  │ 2025-01 │ active │
└───────────────┴────────┴───────┴──────────┴─────────┴────────┘
```

### After (Multiple Goals)
```
Goals Sheet (Multi-Row Model):
┌───────────────┬────────┬───────┬──────────┬─────────┬───────────┬──────────────┐
│ Name          │ Target │ Saved │ Deadline │ Created │ Status    │ LastModified │
├───────────────┼────────┼───────┼──────────┼─────────┼───────────┼──────────────┤
│ Goa Trip      │ 50000  │ 50000 │ 2026-01  │ 2025-01 │ completed │ 2025-01-15   │
├───────────────┼────────┼───────┼──────────┼─────────┼───────────┼──────────────┤
│ Car Fund      │ 200000 │ 75000 │ 2026-06  │ 2025-01 │ active    │ 2025-01-20   │
├───────────────┼────────┼───────┼──────────┼─────────┼───────────┼──────────────┤
│ Emergency     │ 100000 │ 0     │          │ 2025-01 │ active    │ 2025-01-20   │
└───────────────┴────────┴───────┴──────────┴─────────┴───────────┴──────────────┘
```

**Key Differences:**
- Multiple rows instead of single row
- Status column tracks lifecycle: `active` → `completed` → `deleted`
- `LastModified` tracks when goal was last updated
- Goals persist after deletion (status="deleted")

---

## Function Signatures

### Removed Functions
```python
# ❌ OLD - Single goal model
def get_goal() -> dict | None

def delete_goal(username: str) -> bool

def add_to_goal(amount: float, username: str) -> tuple[dict, bool]
```

### New Functions
```python
# ✅ NEW - Multiple goal model
def get_all_goals(status_filter: str = None) -> list[dict]
    # Get all goals, optionally filter by status

def get_goal_by_name(name: str) -> dict | None
    # Get specific goal by exact name match

def get_active_goals() -> list[dict]
    # Convenience: all active goals

def get_completed_goals() -> list[dict]
    # Convenience: all completed goals

def create_goal(name: str, target: float, deadline: str = "") -> dict
    # Create new goal (no replacement, checks for duplicates)

def add_to_goal(goal_name: str, amount: float, username: str) -> tuple[dict | None, bool]
    # Add to specific goal (NEW signature with goal_name)

def break_goal(goal_name: str, username: str = "goal") -> bool
    # Delete goal and refund amount (replaces delete_goal)
```

### Updated Function
```python
def get_balance(user_id: str = None) -> dict
    # Now includes goal totals in returned dict

def get_summary(user_id: str = None) -> dict
    # Unchanged, goals excluded from income/expense calculations
```

---

## Goal Lifecycle State Machine

```
┌─────────┐
│ created │  ← /goal set "Name" | 50000
└────┬────┘
     │
     ▼
┌──────────────────────────────────────┐
│ active                               │
│ - Can receive deposits               │
│ - Visible in /goal list              │
│ - Counted in balance                 │
│ - Shows in goal selection buttons    │
└────┬─────────────┬──────────────────┘
     │             │
     │ (goal met)  │ /goal break
     │             │
     ▼             ▼
┌──────────────────┐  ┌─────────────────────────────────┐
│ completed        │  │ deleted                         │
│ - Locked state   │  │ - Funds refunded as income      │
│ - No deposits    │  │ - Removed from active list      │
│ - Stays in sheet │  │ - Preserved in sheet history    │
│ - Refundable     │  │ - Cannot be reactivated         │
└──────────────────┘  └─────────────────────────────────┘
```

---

## Message Handler Flow

### Before (Single Goal)
```
User Message
     │
     ├─→ Is there an active goal? (get_goal())
     │   ├─→ Yes: Check if goal deposit detected
     │   │   ├─→ Yes: Add to single goal
     │   │   └─→ No: Process as normal transaction
     │   └─→ No: Process as normal transaction
     │
     └─→ Extract transaction and save
```

### After (Multiple Goals)
```
User Message
     │
     ├─→ Are there active goals? (get_active_goals())
     │   ├─→ Yes: Check if goal deposit detected
     │   │   ├─→ Yes (amount found):
     │   │   │   ├─→ Try to match goal hint from NLP
     │   │   │   ├─→ If multiple goals & no match:
     │   │   │   │   └─→ Show button selection
     │   │   │   └─→ If single goal or match found:
     │   │   │       └─→ Auto-deposit to matched goal
     │   │   └─→ No: Process as normal transaction
     │   └─→ No: Process as normal transaction
     │
     └─→ Extract transaction and save
```

---

## Goal Completion Behavior

### Before (Auto-Booking)
```
User deposits enough to complete goal
     │
     ├─→ Add to goal (Status: active → completed)
     ├─→ Log deposit as "Goal Saving" expense
     ├─→ Automatically log full amount as "Goal Achieved" income ⚠️
     │
     └─→ Result: Amount effectively returns to net balance immediately
```

### After (Locked State)
```
User deposits enough to complete goal
     │
     ├─→ Add to goal (Status: active → completed)
     ├─→ Log deposit as "Goal Saving" expense
     ├─→ Do NOT auto-book as income ✅
     │
     └─→ Result: Amount stays in completed goal (locked)
              User must explicitly break goal to get refund
```

**Transaction Logs for ₹50,000 Goal Completion:**

Before:
```
Transaction 1: Type=expense, Category=Goal Saving, Amount=50000
Transaction 2: Type=income, Category=Goal Achieved, Amount=50000  ← Auto-booked
Net effect: 0 impact on net balance
```

After:
```
Transaction 1: Type=expense, Category=Goal Saving, Amount=50000
No auto-income transaction created ✅
Net effect: -50000 (temporarily locked in goal)

When breaking goal later:
Transaction 2: Type=income, Category=Goal Refund, Amount=50000  ← Manual return
Net effect: back to 0
```

---

## Command Handler Architecture

### Command Routing
```python
/goal [subcommand]
    │
    ├─→ (no subcommand)  → _goal_status()      # Show all goals
    ├─→ list             → _goal_list()         # Alias
    ├─→ set <args>       → _goal_set()          # Create new goal
    ├─→ view <name>      → _goal_view()         # View specific goal
    ├─→ add <name> <amt> → _goal_add()          # Add to specific goal
    └─→ break <name>     → _goal_break()        # Delete goal

Callbacks:
    │
    ├─→ goal_deposit:<name>     → Select which goal to deposit to
    └─→ goal_break:<name>|yes/no → Confirm goal deletion
```

---

## Balance Display Architecture

### Before
```
/balance
  └─→ get_balance()
      └─→ Net Balance: ₹X,XXX
```

### After
```
/balance
  └─→ get_balance()           [net, monthly info]
  └─→ get_active_goals()      [active goal list]
  └─→ get_completed_goals()   [completed goals]
      └─→ Shows:
          1. Net balance
          2. Monthly income/expense
          3. Active goals with progress
          4. Completed goals (locked amounts)
          5. Total locked in completed goals
```

---

## Data Consistency

### Goal Name Uniqueness
- Enforced at creation: `get_goal_by_name()` check before create
- Case-insensitive matching
- Error if duplicate exists

### Status Transitions
- Valid: `active` → `completed` or `deleted`
- Invalid transitions prevented
- Cannot reactivate deleted goals

### Refund Logic
- On break: Only if saved amount > 0
- Logged as "Goal Refund" income transaction
- Amount immediately available in net balance

---

## NLP Integration Changes

### Goal Detection Prompt
```
Before: Returns {is_goal_deposit, amount}
After:  Returns {is_goal_deposit, amount, goal_hint}
```

### Goal Hint Matching Algorithm
```
1. Extract goal_hint from NLP response
2. If no hint → show all active goals (button selection)
3. If hint exists:
   a. Check if any active goal name contains hint (case-insensitive)
   b. If exact match found → auto-deposit
   c. If multiple matches → show button selection
   d. If no match → show all active goals (button selection)
```

### Example Matching
```
Message: "saved 1000 for goa trip"
NLP returns: {is_goal_deposit: true, amount: 1000, goal_hint: "goa"}

Goal check:
- Active goals: ["Goa Trip", "Car Fund", "Emergency Fund"]
- Match: "goa" in "Goa Trip" ✓
- Auto-deposit to "Goa Trip"
```

---

## Backward Compatibility

### Existing Single Goal Migration
1. **Read**: Existing single goal in row 2 remains as-is
2. **Status**: Will have status="active" (or "completed" if was complete)
3. **New goals**: Added as rows 3, 4, 5...
4. **Commands**: Old goal commands won't work (required breaking changes)

### Data Schema Migration
```
Old Headers: [Name, Target, Saved, Deadline, Created, Status]
New Headers: [Name, Target, Saved, Deadline, Created, Status, LastModified]
```

- LastModified added as column 7
- Existing goals default to LastModified = Created date on first read
- Automatically updated on any modification

---

## Performance Considerations

### Query Performance
- `get_all_goals()`: O(n) scan of all rows
- `get_goal_by_name()`: O(n) scan, stops at first match
- Cached via `_goal_sheet` global (invalidated on writes)

### Optimization: If needed later
- Could index goals by name
- Could cache active goals (invalidate on create/update/delete)
- Currently assumes < 100 goals (acceptable for personal finance)

### Sheet API Calls
- Per operation: 1-2 API calls (read + update)
- Caching reduces redundant reads within same request
- No N+1 queries (goal reads are batched)

---

## Error Handling

### New Error Cases
1. **Duplicate goal name** → Reject at creation
2. **Goal not found** → Return None, user gets error message
3. **Invalid status** → Blocked at database layer
4. **Overpayment** → Checked before deposit, user gets amount limit

### Existing Error Cases (Preserved)
- Missing credentials
- Groq API errors
- Sheet API errors
- Invalid amounts/dates

---

## Summary of Key Changes

| Aspect | Before | After |
|--------|--------|-------|
| **Data Model** | Single row | Multi-row |
| **Goal Completion** | Auto-income | Locked state |
| **Goal Deletion** | Refund only | Full lifecycle tracking |
| **Command Signature** | `/goal add <amt>` | `/goal add <name> <amt>` |
| **Multiple Goals** | Not supported | Fully supported |
| **Natural Language** | Simple amount extract | Hint + goal matching |
| **Balance Display** | Net only | Net + goals breakdown |
| **Status Tracking** | Binary | Lifecycle (active/completed/deleted) |
| **History** | Lost | Preserved |

