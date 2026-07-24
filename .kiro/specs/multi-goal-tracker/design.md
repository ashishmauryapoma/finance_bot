# Multi-Goal Tracker Feature - Design Document

## Overview

Transform the Telegram Finance Bot from supporting a single savings goal to supporting unlimited concurrent goals. This enables users to manage multiple savings objectives simultaneously with independent tracking, completion states, and fund locking mechanisms.

## Architecture & Data Model

### Multi-Row Goals Sheet

Replaces the single-row model with a flexible multi-row structure:

| Column | Name | Type | Purpose |
|--------|------|------|---------|
| 1 | Name | String | Unique goal identifier |
| 2 | Target | Float | Savings target amount |
| 3 | Saved | Float | Current saved amount |
| 4 | Deadline | String | Optional target date (YYYY-MM-DD) |
| 5 | Created | String | Creation timestamp |
| 6 | Status | Enum | Lifecycle state: active, completed, deleted |
| 7 | LastModified | String | Last update timestamp |

### Goal Lifecycle State Machine

```
created → active ──→ completed  (locked state, manual break required)
                 └─→ deleted    (refunded, history preserved)
```

**Status Details:**
- **active**: Accepts deposits, visible in goal list
- **completed**: Locked state after reaching target, cannot accept deposits
- **deleted**: Marked as deleted (not removed), funds refunded as income

## Core Functional Components

### 1. Multiple Goals Support
- **Unlimited concurrent goals**: No artificial limit on active goals
- **Unique naming**: Goal names must be unique (case-insensitive)
- **Independent tracking**: Each goal maintains its own saved/target state
- **Lifecycle management**: Track goal from creation through completion/deletion

### 2. Goal Completion Behavior
- **Locked, not auto-returned**: When goal reaches target, funds stay locked in goal
- **No auto-income**: Unlike old system, NO automatic "Goal Achieved" income transaction
- **Manual break mechanism**: User must explicitly break goal to get funds back
- **Break creates income**: Breaking a goal logs "Goal Refund" income transaction

### 3. Enhanced Balance Command
- **Net balance display**: Shows current available balance (excluding locked goals)
- **Active goals breakdown**: Lists all active goals with progress percentages
- **Completed goals section**: Shows locked goals with total locked amount
- **Monthly summary**: Income/expense breakdown for current month
- **Forecasting**: Daily amount needed to reach each deadline

### 4. Command Interface
Commands follow `/goal [subcommand]` pattern:

| Command | Behavior |
|---------|----------|
| `/goal` or `/goal list` | Show all active + completed goals |
| `/goal set "Name" \| Amount \| [Deadline]` | Create new goal |
| `/goal view "Name"` | View specific goal details |
| `/goal add "Name" Amount` | Manually deposit to goal |
| `/goal break "Name"` | Delete goal with confirmation, refund balance |

### 5. Natural Language Goal Detection
- **Smart matching**: Groq extracts goal hint from user message
- **Auto-deposit for single goal**: If only one active goal, auto-deposits without selection
- **Hint-based matching**: Attempts to match extracted hint to goal names
- **Button fallback**: Shows goal selection buttons if hint matches multiple goals
- **Whitespace handling**: Treats whitespace-only text as invalid goal hints

### 6. Goals Sheet Structure
Seven-column schema enabling:
- Independent goal tracking and status
- Full audit trail with timestamps
- Completion vs deletion differentiation
- Progress calculation and forecasting

## Implementation Details

### Goal Creation
- Check for duplicate names (case-insensitive)
- Reject if duplicate exists
- Initialize status as "active"
- Set created and LastModified to current timestamp

### Goal Modification
- Add to goal only if status is "active"
- Prevent overpayment (reject deposits exceeding remaining amount)
- Update Saved amount atomically
- Mark status as "completed" when Saved >= Target
- Update LastModified on any change

### Goal Deletion (Break)
- Mark status as "deleted" (soft delete)
- Log refund transaction as "Goal Refund" income
- Make refunded amount immediately available in balance
- Preserve goal row in sheet for history

### Goal Querying
- Query by name (exact match, case-insensitive)
- Query by status (active, completed, deleted)
- Batch query all goals
- Cache results to minimize API calls

### Balance Calculation
- Net balance = Total income - Total expenses - Total in active goals
- Completed and deleted goals excluded from net balance
- Goal refunds are logged as income transactions

### Natural Language Processing
- Extract is_goal_deposit (boolean)
- Extract amount (float)
- Extract goal_hint (string, may be empty or whitespace)
- Use hint to match against active goal names
- Case-insensitive matching with partial name matching

## Backward Compatibility

### Existing Single Goal Migration
- Existing single goal in sheet remains as-is
- Automatically assigned status based on saved vs target
- New goals appended as additional rows
- All existing queries updated to handle multi-row data

### Data Schema Migration
- LastModified column added (column 7)
- Existing goals get LastModified = Created on first read
- No data loss or destructive changes

## Error Handling

### New Error Cases
- Duplicate goal name detection at creation
- Goal not found errors (returns None, user gets error message)
- Invalid status transitions (blocked at database layer)
- Overpayment protection (reject deposits exceeding remaining amount)

### Preserved Error Cases
- Missing authentication credentials
- Groq/NLP API errors
- Google Sheets API errors
- Invalid amount or date formats

## Testing Strategy

### Property-Based Testing Focus Areas
- Goal creation and retrieval
- Multi-goal independence
- Status transitions and completeness
- Natural language goal matching
- Balance calculations with multiple goals
- Goal refund transactions

### Example-Based Testing Focus Areas
- Specific command interactions
- Error messages for duplicate goals
- Button selection UI behavior
- Zero-deadline goal handling
- Empty goal list scenarios

## Performance Considerations

### Query Optimization
- O(n) scan for goal lookups (acceptable for < 100 goals)
- Caching via module-level _goal_sheet variable
- Cache invalidation on create/update/delete operations

### API Call Efficiency
- Batch goal reads within single request
- No N+1 query patterns
- Minimize Sheet API calls (1-2 per operation)

## Data Consistency Guarantees

- Goal name uniqueness enforced
- Valid status transitions guaranteed
- Atomic goal modifications
- Transaction logging for all state changes
- Deletion is soft (data preserved, status marked deleted)

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Goal Creation and Retrieval

*For any* new goal with unique name and valid target amount, creating and then retrieving the goal by name should return the same goal data.

**Validates: Requirement 1.1, 6.1, 6.2, 7.1**

### Property 2: Multiple Goals Independence

*For any* set of active goals, deposits to one goal should not affect the saved amount of other goals.

**Validates: Requirement 1.2, 1.3**

### Property 3: Completion Locks Funds

*For any* active goal where saved amount equals or exceeds target, transitioning status to completed should prevent further deposits.

**Validates: Requirement 2.1, 2.2**

### Property 4: Balance Calculation with Multiple Goals

*For any* set of active and completed goals, net balance should equal total income minus total expenses minus all active goal amounts.

**Validates: Requirement 3.1, 3.2, 9.1**

### Property 5: Goal Refund Restores Balance

*For any* goal with funds, breaking it should create an income transaction and make those funds available in net balance.

**Validates: Requirement 2.3, 2.4, 12.2, 12.3, 12.4**

### Property 6: Natural Language Goal Matching

*For any* message with goal hint and single active goal, the system should auto-deposit without showing button selection.

**Validates: Requirement 5.1, 5.2**

### Property 7: Goals Sheet Consistency

*For any* goal operation, the goals sheet should have exactly 7 columns with consistent structure.

**Validates: Requirement 6.1, 6.2**

### Property 8: Status Transition Validity

*For any* goal, status should only transition from active to completed or deleted, never in reverse.

**Validates: Requirement 8.4, 8.5**

### Property 9: Unique Goal Names

*For any* set of active goals, no two goals should have the same name (case-insensitive comparison).

**Validates: Requirement 1.1, 7.1**

### Property 10: Command Route Coverage

*For any* valid goal command, the command router should invoke the correct handler function.

**Validates: Requirement 4.1, 4.2, 4.3, 4.4, 4.5**

