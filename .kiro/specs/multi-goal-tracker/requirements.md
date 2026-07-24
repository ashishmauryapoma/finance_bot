# Multi-Goal Tracker - Requirements Document

## Introduction

This document specifies requirements for adding multiple concurrent savings goals support to the Telegram Finance Bot. Currently, the bot supports one active savings goal. This feature enables unlimited concurrent goals with independent tracking, completion states, and fund locking mechanisms. Each goal maintains its own save progress, deadline, and status throughout its lifecycle from creation through completion or deletion.

---

## Glossary

- **System**: Telegram Finance Bot multi-goal tracker subsystem
- **Goal**: A named savings objective with target amount, optional deadline, and current saved amount
- **Active Goal**: A goal with status = "active" that can receive deposits
- **Completed Goal**: A goal with status = "completed" where saved amount = target; funds are locked until goal is broken
- **Deleted Goal**: A goal with status = "deleted"; marked as deleted but preserved in sheet history; funds have been refunded
- **Goal Refund**: Income transaction created when a goal is broken, returning locked funds to net balance
- **Goal Hint**: Natural language keyword extracted by NLP to assist with matching goals
- **Net Balance**: Total income minus total expenses minus all active goal amounts
- **Locked Funds**: Amount saved in completed goals; not counted toward net balance
- **Goal Name**: Unique identifier for a goal (case-insensitive matching)
- **Goal Sheet**: Google Sheet with 7 columns tracking all goals and their state
- **Status**: Lifecycle state of a goal (active, completed, deleted)

---

## Requirements

### Requirement 1: Multiple Goals Support

**User Story:** As a user, I want to create and manage unlimited concurrent savings goals, so that I can save toward multiple objectives simultaneously without replacing existing goals.

#### Acceptance Criteria

1. WHEN a user creates a new goal with a unique name THEN THE System SHALL add that goal to the Goals sheet as a new row without affecting existing goals
2. WHEN a user adds a new goal while other goals exist THEN THE System SHALL maintain all existing goal data and allow independent deposits to each goal
3. WHEN there are multiple active goals THEN THE System SHALL allow the user to view all goals together with their individual progress
4. WHEN the system displays goals THEN THE System SHALL show each goal's name, target amount, current saved amount, and progress percentage

#### Edge Cases

- Creating a goal with the same name as an existing goal (case-insensitive match) should be rejected with error message
- Creating a goal with zero or negative target amount should be rejected
- Creating a goal with invalid deadline format (not YYYY-MM-DD) should be rejected
- Empty goal name should be rejected
- System should handle transition from zero goals to first goal cleanly

---

### Requirement 2: Goal Completion and Fund Locking

**User Story:** As a user, I want my completed goal funds to remain locked until I explicitly break the goal, so that I don't accidentally spend from completed savings.

#### Acceptance Criteria

1. WHEN a goal's saved amount reaches its target amount THEN THE System SHALL mark the goal status as "completed"
2. WHEN a goal is completed THEN THE System SHALL prevent new deposits to that goal and display a "locked" indicator
3. WHEN a goal completes THEN THE System SHALL NOT create an automatic income transaction (unlike old system)
4. WHEN a user breaks a completed goal THEN THE System SHALL mark the goal as "deleted", log a "Goal Refund" income transaction, and make the funds immediately available in net balance
5. WHEN a user breaks a goal with zero saved amount THEN THE System SHALL complete the break operation without creating a transaction

#### Edge Cases

- Depositing exactly the remaining amount should mark goal as completed
- Attempting to deposit after completion should return error message
- Breaking a goal should show confirmation dialog
- Breaking a goal with no saved amount should not create income transaction
- Breaking an already deleted goal should return error message
- System should handle goal completion during same operation as deposit

---

### Requirement 3: Enhanced Balance Command

**User Story:** As a user, I want to see my net balance along with a breakdown of money in goals, so that I understand my available funds and goal progress at a glance.

#### Acceptance Criteria

1. WHEN the user views their balance THEN THE System SHALL display the net available balance (excluding active goal amounts)
2. WHEN the user views their balance AND there are active goals THEN THE System SHALL show each active goal with progress bar, saved/target amounts, and days remaining
3. WHEN the user views their balance AND there are completed goals THEN THE System SHALL show completed goals with "locked" status and total locked amount
4. WHEN the user views their balance THEN THE System SHALL include this month's income and expense totals
5. WHEN a goal has a deadline THEN THE System SHALL calculate and display daily amount needed to reach goal by deadline
6. WHEN a goal has no deadline THEN THE System SHALL display goal without deadline information

#### Edge Cases

- Balance display with zero goals should show only net balance
- Balance display with only completed goals should show no active goals section
- Balance display with no income/expense this month should show zero values
- Display should handle goals with names up to 50 characters
- Display should handle very large goal amounts (millions)
- Display should handle goals created more than 365 days ago

---

### Requirement 4: Goal Command Interface

**User Story:** As a user, I want to manage goals through clear slash commands, so that I can create, view, modify, and delete goals using familiar Telegram bot syntax.

#### Acceptance Criteria

1. WHEN the user enters `/goal` or `/goal list` THEN THE System SHALL display all active goals followed by all completed goals
2. WHEN the user enters `/goal set "<name>" | <amount> | [deadline]` THEN THE System SHALL create a new goal with the specified name, target amount, and optional deadline (YYYY-MM-DD format)
3. WHEN the user enters `/goal view "<name>"` THEN THE System SHALL display detailed information for that specific goal including progress, deadline, days remaining, and daily savings needed
4. WHEN the user enters `/goal add "<name>" <amount>` THEN THE System SHALL add the specified amount to the named goal's saved amount
5. WHEN the user enters `/goal break "<name>"` THEN THE System SHALL show a confirmation dialog and delete the goal if confirmed

#### Edge Cases

- Command with unquoted goal name containing spaces should fail gracefully
- Command with missing required parameters should show usage help
- Command with invalid amount (non-numeric) should show error message
- Goal name in command should match case-insensitively against stored goals
- Breaking a goal should prevent accidental deletion with confirmation dialog

---

### Requirement 5: Natural Language Goal Detection

**User Story:** As a user, I want to save toward goals using natural language, so that I can deposit amounts without using explicit goal commands.

#### Acceptance Criteria

1. WHEN a user sends a message containing an amount that the NLP detects as a goal-related deposit THEN THE System SHALL extract the amount, detect goal intent, and extract a goal hint from the message
2. WHEN there is a single active goal AND the message contains a detected amount THEN THE System SHALL automatically deposit the amount to that goal without requiring goal selection
3. WHEN there are multiple active goals AND the message contains a detected amount AND the extracted goal hint matches exactly one goal name (case-insensitive, partial match allowed) THEN THE System SHALL automatically deposit the amount to the matched goal
4. WHEN there are multiple active goals AND the message contains a detected amount AND the goal hint is empty or matches multiple goals THEN THE System SHALL show button selection for the user to choose the target goal
5. WHEN the message contains only whitespace in the goal hint field THEN THE System SHALL treat the hint as empty and not attempt matching

#### Edge Cases

- Message with amount but no goal intent should be processed as regular transaction
- Message with goal hint matching multiple goal names should show button selection
- Message in Hindi mixed with English should be processed correctly
- Goal hint should be case-insensitive for matching
- Empty goal hint (only whitespace) should trigger button selection
- Goal hint matching should work with partial goal names
- System should not auto-deposit if goal hint is ambiguous

---

### Requirement 6: Goals Sheet Schema and Structure

**User Story:** As a system architect, I want the goals sheet to have a consistent 7-column schema, so that the data model is maintainable and all goal information is properly persisted.

#### Acceptance Criteria

1. THE Goals sheet SHALL have exactly 7 columns: Name, Target, Saved, Deadline, Created, Status, LastModified
2. THE Name column SHALL contain the unique goal name (enforced at application level)
3. THE Target column SHALL contain the target amount as a numeric value
4. THE Saved column SHALL contain the current saved amount as a numeric value
5. THE Deadline column SHALL contain the target date in YYYY-MM-DD format or be empty if no deadline
6. THE Created column SHALL contain the creation timestamp
7. THE Status column SHALL contain one of: active, completed, deleted
8. THE LastModified column SHALL be updated whenever any goal field is modified
9. WHEN the system reads a goal with an empty LastModified value THEN THE System SHALL treat it as equal to the Created timestamp

#### Edge Cases

- Adding LastModified column to existing sheet should not disrupt data
- Status values other than active/completed/deleted should be prevented
- Negative values in Target or Saved columns should be prevented
- Empty Name column should be prevented
- Duplicate goal names (case-insensitive) should be prevented at creation time
- Very long goal names (>100 characters) should be handled gracefully

---

### Requirement 7: Data Consistency and Validation

**User Story:** As a system architect, I want data consistency guarantees to prevent invalid states, so that the goal tracker maintains data integrity across all operations.

#### Acceptance Criteria

1. WHEN creating a goal THEN THE System SHALL verify the name is unique (case-insensitive) before allowing creation
2. WHEN creating a goal THEN THE System SHALL verify the target amount is greater than zero before allowing creation
3. WHEN adding to a goal THEN THE System SHALL verify the goal's status is "active" before allowing the deposit
4. WHEN adding to a goal THEN THE System SHALL verify the deposit amount does not exceed the remaining target (saved + deposit <= target)
5. WHEN a goal is completed THEN THE System SHALL prevent further deposits to that goal
6. WHEN modifying a goal THEN THE System SHALL update the LastModified timestamp atomically with the data change
7. WHEN reading goals THEN THE System SHALL return consistent data without partial reads

#### Edge Cases

- Concurrent deposits to the same goal should be handled without race conditions
- Goal creation should be atomic (all fields written together or all rolled back)
- Breaking a goal should be atomic (status update and income transaction)
- Zero-amount deposits should be rejected
- Deposits greater than remaining amount should be rejected with informative message

---

### Requirement 8: Goal Lifecycle and Status Transitions

**User Story:** As a system architect, I want status transitions to follow a defined lifecycle, so that goals move through valid states and invalid transitions are prevented.

#### Acceptance Criteria

1. WHEN a goal is first created THEN THE System SHALL set status to "active"
2. WHEN a goal's saved amount reaches its target THEN THE System SHALL transition status from "active" to "completed"
3. WHEN a user breaks a goal THEN THE System SHALL transition status to "deleted"
4. THE System SHALL NOT allow status transitions other than: active→completed, active→deleted, completed→deleted
5. THE System SHALL NOT allow status transitions in reverse (e.g., deleted→active, completed→active)
6. WHEN querying goals by status THEN THE System SHALL only return goals with matching status

#### Edge Cases

- Completing a goal should be idempotent (completing twice should have same effect as once)
- Attempting to delete an already deleted goal should return error message
- Status values in sheet should always be valid (corrupted values should be caught)
- System should prevent any manual status updates except through defined operations

---

### Requirement 9: Balance Calculation with Multiple Goals

**User Story:** As a user, I want accurate balance calculations that account for all goals, so that I know exactly how much money is available for spending.

#### Acceptance Criteria

1. THE System SHALL calculate net balance as: total_income - total_expenses - sum(active_goal_saved_amounts)
2. THE System SHALL exclude completed goals from the net balance calculation
3. THE System SHALL exclude deleted goals from the net balance calculation
4. WHEN displaying completed goals THEN THE System SHALL show total amount locked across all completed goals
5. WHEN a goal is transitioned to completed THEN THE System SHALL immediately update the balance calculations
6. WHEN a goal is broken and refunded THEN THE System SHALL log "Goal Refund" as income transaction and update balance

#### Edge Cases

- Balance with zero active goals should equal: total_income - total_expenses
- Balance with completed goals should show those amounts separately as "locked"
- Balance calculation should handle large numbers without overflow
- Balance should recalculate consistently even with many goals

---

### Requirement 10: Error Handling and User Feedback

**User Story:** As a user, I want clear error messages when operations fail, so that I understand what went wrong and how to fix it.

#### Acceptance Criteria

1. WHEN a user attempts to create a duplicate goal THEN THE System SHALL return error: "Goal '<name>' already exists!"
2. WHEN a user attempts to add to a non-existent goal THEN THE System SHALL return error: "Goal '<name>' not found. Use `/goal list` to see all goals."
3. WHEN a user attempts to add more than the remaining amount THEN THE System SHALL return error with the maximum allowed amount
4. WHEN a user attempts to break a non-existent goal THEN THE System SHALL return error: "Goal '<name>' not found."
5. WHEN a user provides invalid command syntax THEN THE System SHALL return usage help with examples
6. WHEN an invalid status is detected in the sheet THEN THE System SHALL log warning and treat as corruption error

#### Edge Cases

- Error messages should display goal names in user's original casing
- Multiple errors should be reported together where applicable
- Invalid amount should suggest the correct format
- Goal name not found should suggest using /goal list

---

### Requirement 11: Goal Query and Retrieval

**User Story:** As a system component, I want efficient goal queries so that operations complete quickly and minimize API calls.

#### Acceptance Criteria

1. THE System SHALL support querying all goals with optional status filter
2. THE System SHALL support querying a single goal by exact name (case-insensitive matching)
3. THE System SHALL support querying all active goals efficiently
4. THE System SHALL support querying all completed goals efficiently
5. WHEN querying goals THEN THE System SHALL cache results within a request to avoid duplicate reads
6. WHEN modifying any goal THEN THE System SHALL invalidate cache to ensure next query gets fresh data

#### Edge Cases

- Querying when sheet is empty should return empty list, not error
- Querying with special characters in goal name should work correctly
- Case-insensitive matching should handle Unicode properly
- Very large goal lists (100+ goals) should still perform acceptably

---

### Requirement 12: Goal Breaking and Refund Workflow

**User Story:** As a user, I want breaking a goal to refund my money safely, so that I can reclaim locked funds with clear confirmation.

#### Acceptance Criteria

1. WHEN a user executes `/goal break "<name>"` THEN THE System SHALL show a confirmation dialog with the refund amount
2. WHEN the user confirms goal break THEN THE System SHALL mark the goal status as "deleted"
3. WHEN the user confirms goal break THEN THE System SHALL create an income transaction with category "Goal Refund" for the saved amount
4. WHEN the user confirms goal break THEN THE System SHALL make the refunded amount immediately available in net balance
5. WHEN the user cancels the break confirmation THEN THE System SHALL not modify any goal data

#### Edge Cases

- Breaking a goal with zero saved amount should complete without error but not create transaction
- Breaking a goal should be idempotent (breaking twice returns error on second attempt)
- Refund should appear immediately in balance (no processing delay)
- Confirmation dialog should clearly show goal name and refund amount

---

### Requirement 13: Goal Deadline Handling

**User Story:** As a user, I want deadline support for goals, so that I can set target dates and track progress toward them.

#### Acceptance Criteria

1. WHEN creating a goal THEN THE System SHALL accept an optional deadline in YYYY-MM-DD format
2. WHEN a goal has a deadline THEN THE System SHALL display days remaining until the deadline
3. WHEN a goal has a deadline AND days remaining > 0 THEN THE System SHALL calculate daily amount needed as: (target - saved) / days_remaining
4. WHEN the current date equals the deadline date THEN THE System SHALL display 0 days remaining
5. WHEN a goal has no deadline THEN THE System SHALL omit deadline information from displays
6. WHEN the deadline date is in the past THEN THE System SHALL display negative days remaining or mark as "overdue"

#### Edge Cases

- Deadline should handle leap years correctly
- Deadline calculation should use current date, not creation date
- Invalid date format should be rejected at creation time
- Goals with past deadlines should still function normally but show as overdue
- Deadline change should not be supported (break and recreate required)

---

## Testing Strategy

### Property-Based Testing Focus

- Goal creation and retrieval invariants
- Multi-goal independence properties
- Status transition validity across many goal combinations
- Natural language goal matching with various message formats
- Balance calculations with varied goal configurations
- Refund transaction logging consistency

### Example-Based Testing Focus

- Specific command interactions (e.g., `/goal set "Test" | 1000`)
- Error message verification for duplicate goals
- Button selection UI behavior with specific goals
- Edge case handling (zero deadlines, very large amounts)
- Empty goal list scenarios
- Status display formats

---

