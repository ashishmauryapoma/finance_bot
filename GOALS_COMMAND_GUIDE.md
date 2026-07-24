# Multiple Goals - Command Usage Guide

## Quick Reference

### View Goals
```
/goal                    # Show all active + completed goals
/goal list               # Same as above
/goal view "Trip"        # View specific goal details
```

### Create Goals
```
/goal set "Goa Trip" | 50000 | 2026-12-01
/goal set "Car Fund" | 200000              # Without deadline
/goal set "Emergency Fund" | 100000 | 2025-12-31
```

### Add to Goals

#### Method 1: Explicit Command
```
/goal add "Goa Trip" 5000
/goal add "Car Fund" 25000
```

#### Method 2: Natural Language (Auto-Detected)
```
I saved 5000 for my trip
Depositing 3000 toward the car fund
Added 10000 for emergency savings
```

- If **only 1 active goal**: Auto-deposits ✅
- If **multiple goals**: Shows button selection
- Groq tries to match goal name from message hint

### Manage Goals
```
/goal break "Goa Trip"      # Delete goal & refund balance
/goal break "Car Fund"      # With confirmation dialog
```

### View Balance
```
/balance

Output:
🟢 Net Balance: ₹125,000
────────────────────────────
📅 This Month:
   📥 Income: ₹50,000
   📤 Expenses: ₹25,000
   Net: ₹25,000

✅ Active Goals (2):
   • Goa Trip: ₹10,000/₹50,000 (20%) — ₹40,000 to go
   • Car Fund: ₹75,000/₹200,000 (37%) — ₹125,000 to go
   💰 Total in Active: ₹85,000

✨ Completed Goals (1):
   🔒 Emergency Fund: ₹100,000 (locked)
   🔐 Total Locked: ₹100,000
────────────────────────────
```

---

## Detailed Usage Scenarios

### Scenario 1: Creating Your First Goals

```
User: /goal set "Goa Trip" | 50000 | 2026-12-01
Bot:
✅ Goal created!

🎯 Goa Trip
════════════════════════════
💰 Saved:    ₹0.00 / ₹50,000.00
📊 Progress: [░░░░░░░░░░] 0.0%
📅 Deadline: 2026-12-01 (320 days left)

💡 Need:      ₹156/day to reach goal
════════════════════════════
```

```
User: /goal set "Car Fund" | 200000 | 2026-06-01
Bot:
✅ Goal created!

🎯 Car Fund
════════════════════════════
💰 Saved:    ₹0.00 / ₹200,000.00
📊 Progress: [░░░░░░░░░░] 0.0%
📅 Deadline: 2026-06-01 (150 days left)

💡 Need:      ₹1,333/day to reach goal
════════════════════════════
```

---

### Scenario 2: Adding Savings via Natural Language

#### Single Goal (Auto-Deposit)
```
User: "saved 5000 for trip"
Bot:
🎯 Goal deposit saved! ₹5,000.00 logged.

🎯 Goa Trip
════════════════════════════
💰 Saved:    ₹5,000.00 / ₹50,000.00
📊 Progress: [███░░░░░░░] 10.0%
📅 Deadline: 2026-12-01 (320 days left)

💡 Need:      ₹140/day to reach goal
════════════════════════════
```

#### Multiple Goals (Interactive Selection)
```
User: "i put 10000 aside"
Bot:
💡 Which goal should I add ₹10,000 to?

[💰 Goa Trip (₹5,000/₹50,000)]
[💰 Car Fund (₹0/₹200,000)]

(User clicks "Goa Trip")

Bot:
✅ ₹10,000.00 added to Goa Trip

🎯 Goa Trip
════════════════════════════
💰 Saved:    ₹15,000.00 / ₹50,000.00
📊 Progress: [██████░░░░] 30.0%
📅 Deadline: 2026-12-01 (320 days left)

💡 Need:      ₹109/day to reach goal
════════════════════════════
```

---

### Scenario 3: Goal Completion (Locked, No Auto-Booking)

```
User: /goal add "Goa Trip" 35000
Bot:
➕ Deposit logged

🏆 Goal Complete!
════════════════════════════
🎉 You've saved ₹50,000.00 for Goa Trip!
Funds locked in goal until you break it.
Time to make it happen! 🚀
════════════════════════════
```

**Key Difference from Old System:**
- ❌ Old: Auto-booked ₹50,000 as "Goal Achieved" income
- ✅ New: Funds remain locked in goal. No income transaction created.

Check `/balance`:
```
✨ Completed Goals (1):
   🔒 Goa Trip: ₹50,000 (locked)
   🔐 Total Locked: ₹50,000
```

---

### Scenario 4: Breaking a Completed Goal

```
User: /goal break "Goa Trip"
Bot:
🗑️ Delete goal "Goa Trip"?

💰 ₹50,000.00 will be refunded to your balance.

This cannot be undone.

[✅ Yes, break it] [❌ No, keep it]

(User clicks "Yes, break it")

Bot:
🗑️ Goal deleted.

💰 ₹50,000.00 refunded to your balance.
```

**Result:**
- Goal marked as "deleted" in sheet (history preserved)
- ₹50,000 logged as "Goal Refund" income transaction
- Available in net balance immediately

Check `/balance`:
```
🟢 Net Balance: ₹50,000
```

---

### Scenario 5: Viewing All Goals

```
User: /goal
Bot:
🎯 Your Savings Goals
────────────────────────────
✅ Active Goals:
1. Car Fund
   [████░░░░░░] 30.0%
   ₹60,000 / ₹200,000 (150d left)

2. Emergency Fund
   [██░░░░░░░░] 10.0%
   ₹10,000 / ₹100,000 

📊 Active Total: ₹70,000 / ₹300,000

✨ Completed Goals:
1. 🔒 Vacation Savings — ₹30,000 (locked)

🔐 Locked in Completed: ₹30,000
────────────────────────────
```

---

### Scenario 6: Viewing Specific Goal

```
User: /goal view "Car Fund"
Bot:
✅ Car Fund
════════════════════════════
💰 Saved:    ₹60,000.00 / ₹200,000.00
📊 Progress: [████░░░░░░] 30.0%
📅 Deadline: 2026-06-01 (150 days left)
📌 Created:   15-01-2025

💡 Need:      ₹933/day to reach goal
════════════════════════════
```

```
User: /goal view "Vacation Savings"
Bot:
✨ Vacation Savings
════════════════════════════
💰 Saved:    ₹30,000.00 / ₹30,000.00
📊 Progress: [██████████] 100.0%
📅 Deadline: 2025-12-31 
📌 Created:   01-12-2024

🔒 Status: Locked — Funds held in this goal
Use `/goal break Vacation Savings` to return ₹30,000.00 to your balance
════════════════════════════
```

---

### Scenario 7: Overpayment Protection

```
User: "saving 45000 for car fund"
(Goal has ₹55,000/₹60,000, only ₹5,000 remaining)

Bot:
⚠️ Deposit failed — amount exceeds goal limit!

💰 Already saved: ₹155,000.00
🎯 Target: ₹200,000.00
📌 Only ₹45,000.00 more needed to complete this goal.

Please deposit ₹45,000.00 or less.
```

---

### Scenario 8: Error Handling

#### Goal Not Found
```
User: /goal add "Dream House" 10000
Bot:
❌ Goal 'Dream House' not found.

Use `/goal list` to see all goals.
```

#### Duplicate Goal Name
```
User: /goal set "Car Fund" | 100000
(Car Fund already exists)

Bot:
⚠️ Goal 'Car Fund' already exists!

Use a different name or use `/goal break Car Fund` to delete it first.
```

#### Invalid Amount
```
User: /goal add "Car Fund" xyz
Bot:
⚠️ Invalid amount. Use a plain number like `2000`.
```

---

## Tips & Tricks

### ✨ Natural Language Works With:
- "saved 1000 for goa" → Detects goal deposit, attempts to match "goa"
- "depositing 5000 toward vacation" → Same behavior
- "goal savings: 2000" → Recognized as goal intent
- Hindi mixed: "mene 3000 trip ke liye bach diya" → Works!

### 💡 Goal Naming Best Practices
- Use clear, short names: "Goa Trip" not "Trip to Goa in December"
- Be consistent: Always use "Car Fund" or always "Car Fund"
- Avoid special characters: Use spaces instead of dashes/underscores

### 🎯 Goal Deadline Formats
- Use ISO format: `2026-12-01` (YYYY-MM-DD)
- System calculates days remaining automatically
- Deadline is optional (use empty for no deadline)

### 🔒 Completed Goals
- Locked until explicitly broken
- Helps prevent accidental spending from goal funds
- Data preserved in sheet even after deletion

---

## FAQ

**Q: Can I edit a goal after creating it?**
A: Not yet. Break it and create a new one.

**Q: What if I have multiple goals with similar names?**
A: Use `/goal view "<exact_name>"` to verify and manage them separately.

**Q: Do completed goals count toward my net balance?**
A: No, only when you break them. They stay "locked" until then.

**Q: Can I see goal history?**
A: All goals (even deleted) are stored in the Goals sheet with status. Check the sheet directly.

**Q: How does natural language matching work?**
A: Groq extracts a keyword hint from your message. If it matches a goal name or is unique enough, it auto-deposits. Otherwise, you get button selection.

**Q: Can I have a goal with no deadline?**
A: Yes! Use `/goal set "Goal Name" | 50000` (omit deadline).
