# Implementation Plan: Multi-Goal Tracker

## Overview

Transform the finance bot from single-goal to multi-goal support by extending the Google Sheets schema to 7 columns, implementing multi-goal query functions, updating command handlers, enhancing NLP for goal detection, and creating new balance display formatting. Implementation proceeds in phases: foundation schema, data layer, command routing, NLP enhancement, balance display, and integration verification.

## Tasks

- [x] 1. Foundation: Update Goals Sheet Schema to 7 Columns
  - [x] 1.1 Update `_get_goal_sheet()` to verify and initialize 7-column structure
    - Add headers: Name, Target, Saved, Deadline, Created, Status, LastModified
    - Verify exact column count during sheet access
    - Create sheet with full 7-column structure if not exists
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [x] 1.2 Migrate `_style_goal_header()` to handle 7-column layout
    - Update header formatting for columns 1–7
    - Apply consistent cell styling across all 7 columns
    - Set appropriate column widths for new columns (Status, LastModified)
    - _Requirements: 6.1_

  - [x] 1.3 Update `_style_goal_data_rows()` for 7-column data formatting
    - Format Status column with alignment and text styling
    - Format LastModified column with timestamp styling
    - Ensure consistent formatting across multi-row data
    - _Requirements: 6.1, 6.6, 6.7_

  - [ ]* 1.4 Write property test for Goals Sheet schema consistency
    - **Property 7: Goals Sheet Consistency**
    - **Validates: Requirements 6.1, 6.2**

- [ ] 2. Data Layer: Implement Multi-Goal Query and Modification Functions
  - [ ] **[IN PROGRESS]** 2.1 Implement `get_all_goals_multi()` to retrieve all goals with status filtering
    - Query all rows in Goals sheet with 7-column structure
    - Support optional status filter (active, completed, deleted)
    - Return list of dicts with all 7 columns
    - Handle empty sheet gracefully
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [ ] **[IN PROGRESS]** 2.2 Implement `get_goal_by_name_multi()` for case-insensitive goal lookup
    - Search Goals sheet by Name column (case-insensitive matching)
    - Return complete goal dict or None if not found
    - Support partial name matching for goal hints
    - _Requirements: 11.2_

  - [ ] **[IN PROGRESS]** 2.3 Implement `validate_goal_uniqueness()` to prevent duplicate goal names
    - Check if goal name already exists (case-insensitive)
    - Return boolean and error message if duplicate
    - Validate before creating new goals
    - _Requirements: 7.1_

  - [ ] 2.4 Implement `create_goal_multi()` to add new goal as new row
    - Generate new row with all 7 columns: Name, Target, Saved, Deadline, Created, Status=active, LastModified
    - Check for duplicate name (case-insensitive)
    - Set Saved=0 for new goals
    - Set Created and LastModified to current timestamp
    - Append row to Goals sheet
    - _Requirements: 1.1, 1.2, 6.1–6.7, 7.1, 8.1_

  - [ ] 2.5 Implement `add_to_goal_multi()` to deposit amount to active goal
    - Validate goal exists and status is "active"
    - Validate deposit does not exceed remaining amount (saved + deposit <= target)
    - Update Saved column atomically
    - Check if saved >= target and transition status to "completed" if so
    - Update LastModified timestamp
    - _Requirements: 2.2, 7.3, 7.4, 7.6, 8.2_

  - [ ] 2.6 Implement `break_goal_multi()` to delete goal and refund funds
    - Validate goal exists
    - Mark goal status as "deleted"
    - Update LastModified timestamp
    - If saved amount > 0, create income transaction with category "Goal Refund"
    - Return boolean success and refund amount for confirmation
    - _Requirements: 2.2, 2.4, 2.5, 12.1–12.4_

  - [ ] 2.7 Implement `get_active_goals_multi()` and `get_completed_goals_multi()`
    - Query all goals with status filter
    - Return lists for easy access by status
    - Cache results to minimize API calls
    - _Requirements: 11.3, 11.4_

  - [ ]* 2.8 Write property test for Goal Creation and Retrieval
    - **Property 1: Goal Creation and Retrieval**
    - **Validates: Requirements 1.1, 6.1, 6.2, 7.1**

  - [ ]* 2.9 Write property test for Multiple Goals Independence
    - **Property 2: Multiple Goals Independence**
    - **Validates: Requirements 1.2, 1.3**

  - [ ]* 2.10 Write property test for Completion Locks Funds
    - **Property 3: Completion Locks Funds**
    - **Validates: Requirements 2.1, 2.2**

  - [ ]* 2.11 Write property test for Unique Goal Names
    - **Property 9: Unique Goal Names**
    - **Validates: Requirements 1.1, 7.1**

- [ ] 3. Data Layer: Update Balance Calculation for Multi-Goal Support
  - [ ] 3.1 Implement `calculate_balance_multi()` for net balance with active goals
    - Calculate: net = total_income - total_expenses - sum(active_goal_saved_amounts)
    - Exclude completed and deleted goals from deduction
    - Return dict with net_balance, total_income, total_expenses
    - _Requirements: 9.1, 9.2, 9.3_

  - [ ] 3.2 Implement `get_locked_amount()` to sum completed goal funds
    - Query all goals with status="completed"
    - Sum their Saved amounts
    - Return total locked amount
    - _Requirements: 3.2, 9.2_

  - [ ] 3.3 Update `get_balance()` in sheets_handler to use multi-goal calculation
    - Replace single-goal balance logic with `calculate_balance_multi()`
    - Include locked_amount in balance response
    - Maintain backward compatibility with existing balance format
    - _Requirements: 3.1–3.5_

  - [ ]* 3.4 Write property test for Balance Calculation with Multiple Goals
    - **Property 4: Balance Calculation with Multiple Goals**
    - **Validates: Requirements 3.1, 3.2, 9.1**

- [ ] 4. Command Handlers: Implement `/goal` Subcommand Routing
  - [ ] 4.1 Refactor `goal_router()` to route all `/goal` subcommands
    - Parse subcommand: list, set, view, add, break
    - Route to appropriate handler function
    - Show usage help if subcommand invalid
    - _Requirements: 4.1–4.5_

  - [ ] 4.2 Implement `_goal_list_multi()` handler for `/goal list` and `/goal`
    - Call `get_active_goals_multi()` and `get_completed_goals_multi()`
    - Use updated formatters to display all goals
    - Show empty state if no goals exist
    - _Requirements: 4.1_

  - [ ] 4.3 Implement `_goal_set_multi()` handler for `/goal set` command
    - Parse command: `/goal set "Name" | Amount | [Deadline]`
    - Validate name is non-empty and unique (case-insensitive)
    - Validate amount > 0
    - Validate deadline format (YYYY-MM-DD) if provided
    - Call `create_goal_multi()` and confirm creation
    - Show error message if validation fails
    - _Requirements: 4.2, 7.1, 7.2_

  - [ ] 4.4 Implement `_goal_view_multi()` handler for `/goal view` command
    - Parse command: `/goal view "Name"`
    - Look up goal by name (case-insensitive)
    - Display detailed goal info with progress bar, deadline, days remaining, daily amount needed
    - Show error if goal not found
    - _Requirements: 4.3_

  - [ ] 4.5 Implement `_goal_add_multi()` handler for `/goal add` command
    - Parse command: `/goal add "Name" Amount`
    - Look up goal by name (case-insensitive)
    - Validate goal status is "active"
    - Validate deposit <= remaining amount
    - Call `add_to_goal_multi()` to update goal
    - Show success confirmation or error message
    - If goal completes, show completion celebration message
    - _Requirements: 4.4, 7.3, 7.4_

  - [ ] 4.6 Implement `_goal_break_multi()` handler for `/goal break` command
    - Parse command: `/goal break "Name"`
    - Look up goal by name (case-insensitive)
    - Show confirmation dialog with refund amount
    - Call `break_goal_multi()` on confirmation
    - Create income transaction for "Goal Refund"
    - Show success message with refund amount
    - Show error if goal not found
    - _Requirements: 4.5, 12.1–12.4_

  - [ ]* 4.7 Write property test for Command Route Coverage
    - **Property 10: Command Route Coverage**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**

- [ ] 5. Goal Handler: Create Multi-Goal Formatters
  - [ ] 5.1 Implement `format_goal_card_multi()` for single goal display
    - Show goal name, target, saved, progress bar, deadline, daily amount needed
    - Show "locked" indicator if goal is completed
    - Show "Goal Refund: ₹X" if goal is deleted
    - _Requirements: 1.3, 1.4, 3.3_

  - [ ] 5.2 Implement `format_goals_list_multi()` for all active + completed goals
    - Display all active goals with progress bars
    - Display all completed goals with "locked" indicator
    - Show summaries: "Active Total", "Locked in Completed"
    - Show empty state if no goals
    - _Requirements: 1.3, 1.4, 3.1–3.3_

  - [ ] 5.3 Implement `format_balance_with_goals()` for enhanced balance display
    - Show net available balance (excluding active goals)
    - Show active goals section with progress bars and daily amounts needed
    - Show completed goals section with locked amounts
    - Show this month's income/expense summary
    - _Requirements: 3.1–3.6_

  - [ ] 5.4 Update `_days_left()` and `_daily_needed()` helpers for deadline calculations
    - Keep existing helpers but ensure they work with new 7-column schema
    - Handle edge cases: past deadlines, same-day deadlines, no deadline
    - _Requirements: 13.3, 13.4, 13.5, 13.6_

  - [ ]* 5.5 Write unit tests for formatter output correctness
    - Test progress bar formatting with various percentages
    - Test daily amount calculations with various deadline scenarios
    - Test empty list formatting
    - _Requirements: 3.1–3.6_

- [ ] 6. NLP Enhancement: Improve Goal Detection for Multi-Goal
  - [ ] 6.1 Enhance `detect_goal_deposit()` to extract goal hints
    - Keep existing amount detection
    - Add goal hint extraction from message text
    - Return dict: {is_goal_deposit: bool, amount: float, goal_hint: str}
    - Handle empty/whitespace goal hints by returning empty string
    - _Requirements: 5.1, 5.5_

  - [ ] 6.2 Implement `match_goal_hint()` to match hints to goal names
    - Compare goal_hint against active goal names (case-insensitive)
    - Support partial name matching
    - Return matched goal name or None if no match or multiple matches
    - _Requirements: 5.3, 5.4_

  - [ ] 6.3 Update `handle_message()` in bot.py to route goal deposits
    - Call `detect_goal_deposit()` on all messages
    - If is_goal_deposit=true and single active goal, auto-deposit without confirmation
    - If is_goal_deposit=true and multiple active goals, match hint to goal
    - If match found, auto-deposit; if no match or multiple matches, show button selection
    - _Requirements: 5.2, 5.3, 5.4_

  - [ ]* 6.4 Write property test for Natural Language Goal Matching
    - **Property 6: Natural Language Goal Matching**
    - **Validates: Requirements 5.1, 5.2**

- [ ] 7. Utils: Add Multi-Goal Balance Display Functions
  - [ ] 7.1 Implement `format_active_goals_breakdown()` for active goals section
    - Format list of active goals with progress bars
    - Include saved/target amounts and deadline info
    - _Requirements: 3.2, 3.3_

  - [ ] 7.2 Implement `format_completed_goals_section()` for locked funds display
    - Format list of completed goals with "locked" indicator
    - Show total locked amount
    - _Requirements: 3.3, 3.4_

  - [ ] 7.3 Implement `format_balance_summary_multi()` for full balance display
    - Combine net balance, active goals, completed goals, and income/expense summary
    - Use new helper functions from 7.1 and 7.2
    - Show daily amounts needed for each goal with deadline
    - _Requirements: 3.1–3.6_

  - [ ]* 7.4 Write unit tests for balance display formatting
    - Test with various goal configurations (zero, one, many goals)
    - Test with completed and deleted goals
    - Test with large amounts and long goal names
    - _Requirements: 3.1–3.6_

- [ ] 8. Integration: Wire Components Together
  - [ ] 8.1 Update `balance` command to use `format_balance_summary_multi()`
    - Replace existing balance display with multi-goal version
    - Ensure backward compatibility with single-goal scenario
    - _Requirements: 3.1–3.6_

  - [ ] 8.2 Update `handle_message()` to call multi-goal goal deposit handlers
    - Integrate NLP goal detection (from 6.3)
    - Route to `_goal_add_multi()` or button selection
    - _Requirements: 5.1–5.5_

  - [ ] 8.3 Verify all `/goal` subcommands work end-to-end
    - Test `/goal list` displays all goals
    - Test `/goal set` creates new goal with 7 columns
    - Test `/goal view` shows goal details
    - Test `/goal add` deposits to goal and transitions status
    - Test `/goal break` refunds and creates income transaction
    - _Requirements: 4.1–4.5_

  - [ ]* 8.4 Write property test for Goal Refund Restores Balance
    - **Property 5: Goal Refund Restores Balance**
    - **Validates: Requirements 2.3, 2.4, 12.2, 12.3, 12.4**

- [ ] 9. Validation: Error Handling and Edge Cases
  - [ ] 9.1 Implement comprehensive error handling for all goal operations
    - Duplicate goal name detection with error message
    - Goal not found handling with suggestion to use `/goal list`
    - Invalid amount handling (negative, zero, exceeding remaining)
    - Invalid deadline format handling
    - _Requirements: 10.1–10.4_

  - [ ] 9.2 Validate command parsing and show usage help
    - Parse `/goal set "Name" | Amount | [Deadline]` format correctly
    - Parse `/goal add "Name" Amount` format correctly
    - Show helpful error messages for malformed commands
    - _Requirements: 10.5_

  - [ ] 9.3 Handle edge cases in goal operations
    - Depositing exactly remaining amount (triggers completion)
    - Breaking a goal with zero saved amount (no transaction created)
    - Breaking already deleted goal (error message)
    - Goal names with special characters or unicode
    - _Requirements: 1.4, 2.5, 7.4_

  - [ ] 9.4 Validate data consistency in Goals sheet
    - Check for invalid status values in sheet
    - Log warnings for corrupted data
    - Ensure all rows have consistent column count
    - _Requirements: 7.7, 10.6_

- [ ] 10. Checkpoint: Verify Core Functionality
  - Run all unit and property tests for data layer (sections 2–3)
  - Run all command routing tests for handlers (section 4)
  - Run all formatter tests for goal display (section 5)
  - Ensure all tests pass, ask the user if questions arise.
  - Ensure no regressions in existing single-goal workflow

- [ ] 11. Integration Testing: Multi-Goal End-to-End Flows
  - [ ] 11.1 Test creating multiple goals and verifying independence
    - Create 3 goals with different targets and deadlines
    - Deposit to each goal separately
    - Verify deposits affect only target goal
    - _Requirements: 1.1, 1.2, 1.3_

  - [ ] 11.2 Test goal completion and locking workflow
    - Create goal with target 1000
    - Deposit 1000, verify status transitions to "completed"
    - Attempt to deposit more, verify error
    - Verify goal shows as locked in display
    - _Requirements: 2.1, 2.2_

  - [ ] 11.3 Test goal breaking and refund workflow
    - Create goal with target 1000, deposit 500
    - Break goal with confirmation
    - Verify status transitions to "deleted"
    - Verify "Goal Refund" income transaction created with 500 amount
    - Verify refunded amount appears in net balance
    - _Requirements: 2.4, 2.5, 12.1–12.4_

  - [ ] 11.4 Test balance calculation with mixed goal states
    - Create: goal1 (active, saved 300/1000), goal2 (completed, saved 500/500), goal3 (active, saved 200/1000)
    - Verify net balance = income - expenses - 300 - 200
    - Verify locked amount = 500
    - _Requirements: 3.1, 9.1–9.3_

  - [ ] 11.5 Test natural language goal deposits with multiple goals
    - Create 2 active goals: "vacation" (1000), "car" (5000)
    - Send message "saved 200 for vacation"
    - Verify goal hint extraction and matching
    - Verify auto-deposit to vacation goal
    - _Requirements: 5.1, 5.2_

  - [ ] 11.6 Test natural language goal deposits with ambiguous hints
    - Create 2 active goals: "vacation" (1000), "vacation-fund" (2000)
    - Send message "saved 200 for vacation"
    - Verify multiple match detected
    - Verify button selection shown to user
    - _Requirements: 5.4_

  - [ ]* 11.7 Write integration test suite covering all flows
    - Test all command sequences from creation to breaking
    - Test balance calculations with various goal combinations
    - Test NLP matching with edge cases
    - _Requirements: 1.1–1.4, 2.1–2.5, 3.1–3.6, 4.1–4.5, 5.1–5.5_

- [ ] 12. Checkpoint: Verify All Tests Pass
  - Run complete test suite (unit, property, integration)
  - Ensure all tests pass, ask the user if questions arise.
  - Verify no regressions in non-goal functionality (transactions, summary, balance)

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Core data layer tasks (2–3) must complete before command handlers (4)
- Command handlers (4) must complete before NLP enhancement (6)
- Formatters (5) and utils (7) work in parallel with handlers (4)
- Integration (8) is a wiring task after all components complete
- All property tests validate the correctness properties defined in design.md
- Goal creation is atomic: either all fields written together or all rolled back
- Status transitions follow strict rules: active→completed, active→deleted only
- Goal names are case-insensitive but should preserve user's casing in displays

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 2, "tasks": ["2.4", "2.5", "2.6", "2.7"] },
    { "id": 3, "tasks": ["3.1", "3.2", "5.1", "5.2", "5.3", "5.4", "6.1", "7.1", "7.2", "7.3"] },
    { "id": 4, "tasks": ["3.3", "4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "6.2"] },
    { "id": 5, "tasks": ["6.3", "8.1", "8.2"] },
    { "id": 6, "tasks": ["1.4", "2.8", "2.9", "2.10", "2.11", "3.4", "4.7", "5.5", "6.4", "7.4", "8.3", "8.4", "9.1", "9.2", "9.3", "9.4"] },
    { "id": 7, "tasks": ["11.1", "11.2", "11.3", "11.4", "11.5", "11.6", "11.7"] }
  ]
}
```
