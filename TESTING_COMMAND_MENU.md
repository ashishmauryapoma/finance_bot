# Testing Command Menu Implementation

## Quick Test (2 minutes)

### Prerequisites
- Telegram bot running (polling or webhook mode)
- Bot is responsive and authenticated
- Telegram client open

### Test Steps

#### 1. **Start the Bot**
```bash
python bot.py
```

**Expected Log Output:**
```
PTB app initialised.
✅ Registered 7 bot commands
Bot command menu registered.
```

#### 2. **Open Telegram**
- Find your bot in Telegram
- Open chat with your bot

#### 3. **Test "/" Autocomplete**
- Type `/` in the message box
- **Expected**: Dropdown appears showing all 7 commands with descriptions

```
Your Telegram Chat:
|─────────────────────────────────────|
| /start     Start bot & login        |
| /recent    Show last 10 transactions|
| /summary   Monthly income/expense.. |
| /balance   View net balance & goals.|
| /goal      Manage savings goals (...)
| /logout    Log out from bot         |
| /help      Show help & all commands |
|─────────────────────────────────────|
```

#### 4. **Test Menu Button**
- Tap the **menu button** (⋮ or hamburger icon) in Telegram
- **Expected**: Same command list appears in the menu

#### 5. **Test Command Execution**
- Tap `/help` from the menu
- **Expected**: Help message displays (unchanged behavior)

- Try `/balance` from the menu
- **Expected**: Balance command executes normally

#### 6. **Verify Descriptions**
Each description should be clear and concise:
- ✓ "Start bot & login" - 18 chars
- ✓ "Show last 10 transactions" - 25 chars
- ✓ "Monthly income/expense summary" - 30 chars
- ✓ "View net balance & goals breakdown" - 34 chars
- ✓ "Manage savings goals (set/add/view/break/list)" - 46 chars
- ✓ "Log out from bot" - 15 chars
- ✓ "Show help & all available commands" - 34 chars

All descriptions are **under 256 character limit** ✓

---

## Detailed Test Cases

### Test Case 1: Basic Menu Display
**Scenario**: User opens bot for first time
1. Open Telegram
2. Type "/" in chat
3. **Expected**: All 7 commands visible with descriptions
4. **Pass**: ✓ if menu appears immediately

---

### Test Case 2: Command Selection from Menu
**Scenario**: User selects command from dropdown
1. Type "/"
2. Tap on `/balance`
3. **Expected**: `/balance` is inserted into text box
4. **Expected**: Message is sent
5. **Expected**: Balance command executes normally
6. **Pass**: ✓ if command works as before

---

### Test Case 3: Mobile Menu Button
**Scenario**: User on mobile device
1. Open bot chat
2. Tap menu icon (⋮)
3. **Expected**: Command menu appears in chat interface
4. **Expected**: All 7 commands are listed with descriptions
5. **Pass**: ✓ if all commands visible without scrolling

---

### Test Case 4: Description Accuracy
**Scenario**: Verify descriptions match actual functionality
1. Type "/" to open menu
2. For each command, verify description is accurate:

| Command | Description | Verification |
|---------|-------------|--------------|
| /start | "Start bot & login" | Starts auth flow ✓ |
| /recent | "Show last 10 transactions" | Shows recent transactions ✓ |
| /summary | "Monthly income/expense summary" | Shows monthly summary ✓ |
| /balance | "View net balance & goals breakdown" | Shows balance & goals ✓ |
| /goal | "Manage savings goals..." | Routes to goal commands ✓ |
| /logout | "Log out from bot" | Logs out user ✓ |
| /help | "Show help & all available commands" | Shows full help ✓ |

**Pass**: ✓ if all descriptions match functionality

---

### Test Case 5: Multiple Bot Instances
**Scenario**: Running multiple bots
- If you have multiple bot tokens, each should register independently
- Each bot should show its own command menu
- No conflicts between bots

**Pass**: ✓ if each bot shows correct commands

---

### Test Case 6: Restart Bot
**Scenario**: Restart bot to verify re-registration
1. Stop bot (Ctrl+C)
2. Wait 2 seconds
3. Start bot again
4. **Expected**: Log shows "✅ Registered 7 bot commands" again
5. Verify commands still work in Telegram

**Pass**: ✓ if commands re-register successfully

---

### Test Case 7: Network Error Handling
**Scenario**: Bot handles command registration failures gracefully
1. Stop bot
2. Disconnect from internet (if testing offline)
3. Start bot
4. **Expected**: Log shows error message but bot continues running
5. Reconnect to internet
6. Restart bot
7. **Expected**: Commands re-register successfully

**Pass**: ✓ if bot runs even if registration fails

---

### Test Case 8: Command Not Found
**Scenario**: User types invalid command
1. Type `/invalid` in chat
2. **Expected**: "Unknown command. Use /help." message
3. **Expected**: `/invalid` is NOT in the menu (correct behavior)

**Pass**: ✓ if only valid commands in menu

---

## Regression Tests

Ensure existing functionality still works:

### Test: Transaction Input
- Send: "spent 500 on food"
- Expected: Transaction logged normally
- Pass: ✓

### Test: Goal Operations
- Command: `/goal list`
- Expected: Goals displayed normally
- Pass: ✓

### Test: Authentication
- Command: `/logout`
- Then: `/start`
- Expected: Password prompt appears
- Pass: ✓

---

## Performance Tests

### Test Case: Command Menu Speed
1. Open bot chat
2. Type "/" and measure time for menu to appear
3. **Expected**: Menu appears within 1 second
4. **Pass**: ✓ if instant or nearly instant

### Test Case: Command Execution Speed
1. Select `/balance` from menu
2. Measure time for response
3. **Expected**: Same speed as manual `/balance` command
4. **Pass**: ✓ if no performance degradation

---

## Cross-Platform Tests

### Desktop Telegram
- [ ] Windows - "/" shows menu with descriptions
- [ ] macOS - "/" shows menu with descriptions
- [ ] Linux - "/" shows menu with descriptions
- [ ] Web (web.telegram.org) - Menu displays correctly

### Mobile Telegram
- [ ] iOS - Menu button shows commands
- [ ] Android - Menu button shows commands
- [ ] "/" autocomplete works

---

## Log Output Validation

### Expected Log Messages

**On Startup:**
```
2024-XX-XX XX:XX:XX - __main__ - INFO - PTB app initialised.
2024-XX-XX XX:XX:XX - __main__ - INFO - ✅ Registered 7 bot commands
2024-XX-XX XX:XX:XX - __main__ - INFO - Bot command menu registered.
```

**On Success:**
```
✅ Registered 7 bot commands
Bot command menu registered.
```

**On Error:**
```
Failed to register commands: [error details]
Bot command menu registered.  (Bot still starts)
```

---

## Success Criteria

✅ All test cases pass
✅ Log shows successful registration
✅ Menu appears when user types "/"
✅ All 7 commands visible in menu
✅ Descriptions are accurate and helpful
✅ Command execution works normally
✅ No performance degradation
✅ Works across all platforms (desktop, mobile, web)
✅ Error handling is graceful
✅ Existing functionality unaffected

---

## Troubleshooting

### Issue: Menu doesn't appear when typing "/"

**Solution 1**: Restart the bot
```bash
# Stop bot (Ctrl+C)
python bot.py
```

**Solution 2**: Check bot permissions
- Ensure bot has "setMyCommands" permission
- Most bots have this by default

**Solution 3**: Clear Telegram cache
- Close Telegram completely
- Clear app cache
- Reopen Telegram

### Issue: Only some commands show

**Solution**: Check bot token is correct
```bash
echo $TELEGRAM_BOT_TOKEN  # Verify token is set
```

### Issue: Descriptions are cut off

**Solution**: Descriptions are limited by Telegram UI
- They display fully in most clients
- No action needed

### Issue: Bot logs error but still runs

**Solution**: This is expected behavior
- Error handling is working correctly
- Try restarting bot to retry registration
- Check network connection

---

## Cleanup After Testing

If you want to clear commands (rarely needed):
```python
# In bot.py, add this temporarily:
await app.bot.delete_my_commands()
```

Then restart bot without this line.

