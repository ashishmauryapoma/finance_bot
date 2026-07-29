# 🚀 Quick Start Guide

Get the Telegram Finance Bot running in **5 minutes**.

---

## ⚡ 5-Minute Setup

### Step 1: Clone & Navigate (1 min)
```bash
cd finance_bot
```

### Step 2: Create Virtual Environment (1 min)
**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies (1 min)
```bash
pip install -r requirements.txt
```

### Step 4: Configure Credentials (1 min)
Create `.env` file:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
GROQ_API_KEY=your_groq_api_key
GOOGLE_SHEETS_CREDENTIALS=./credentials.json
BOT_PASSWORD=your_secure_password
```

### Step 5: Run Bot (1 min)
```bash
python bot.py
```

**Expected output:**
```
PTB app initialised.
✅ Registered 7 bot commands
Bot command menu registered.
Polling mode
```

---

## 📱 Test in Telegram

1. Open Telegram
2. Find your bot
3. Type `/start`
4. See the welcome message
5. Try: `spent 500 on groceries`

---

## 🎯 What's Next?

### If You Want to...

**Understand the project**
→ Read [README.md](./README.md)

**Need complete setup guide**
→ See [PROJECT_SETUP.md](./PROJECT_SETUP.md)

**Deploy to production**
→ Check [PROJECT_SETUP.md#deployment](./PROJECT_SETUP.md#deployment)

**Test features**
→ Follow [TESTING_COMMAND_MENU.md](./TESTING_COMMAND_MENU.md)

**Troubleshoot issues**
→ Use [PROJECT_SETUP.md#troubleshooting](./PROJECT_SETUP.md#troubleshooting)

**Explore features**
→ See [README.md#-usage-guide](./README.md#-usage-guide)

---

## 📋 Prerequisites

Before starting, you need:

1. **Telegram Bot Token**
   - Chat @BotFather on Telegram
   - Type `/start` then `/newbot`
   - Copy the token

2. **Groq API Key**
   - Visit https://console.groq.com
   - Sign up (free)
   - Create API key

3. **Google Sheets Credentials**
   - Create Google Cloud project
   - Enable Google Sheets API
   - Create service account
   - Download JSON credentials

4. **Google Sheet**
   - Create sheet at https://sheets.google.com
   - Share with service account email

---

## 🐛 Quick Troubleshooting

**"TELEGRAM_BOT_TOKEN not set"**
→ Check `.env` file exists with correct token

**"Module not found"**
→ Run `pip install -r requirements.txt`

**"Connection error"**
→ Check internet connection and API keys

**More help**
→ See [DOCUMENTATION_INDEX.md](./DOCUMENTATION_INDEX.md)

---

## 💡 Quick Examples

### Track Expense
```
You: spent 500 on groceries
Bot: ✅ Transaction Saved!
```

### Track Income
```
You: earned 5000 salary
Bot: ✅ Transaction Saved!
```

### Create Goal
```
You: /goal set Trip | 50000 | 2026-12-31
Bot: ✅ Goal created!
```

### Add to Goal
```
You: /goal add Trip 2000
Bot: ✅ ₹2,000.00 deposited & logged
```

### View Reports
```
You: /balance
Bot: Shows net balance and goals
```

---

## 📚 Commands

| Command | What it does |
|---------|-------------|
| `/start` | Start and login |
| `/help` | Show all commands |
| `/recent` | Last 10 transactions |
| `/summary` | Monthly report |
| `/balance` | Balance and goals |
| `/goal` | Manage goals |
| `/logout` | Logout |

---

## ✅ Verification

After setup, verify everything works:

```bash
# Bot is running?
# Should see "Polling mode" in console

# Commands working?
# Open Telegram and type /help

# Transactions logging?
# Send "spent 100 on test"
# Check Google Sheet

# Goals working?
# Try /goal list
# Should show success
```

---

## 📞 Need Full Help?

- **Setup issues?** → [PROJECT_SETUP.md](./PROJECT_SETUP.md)
- **Usage questions?** → [README.md](./README.md)
- **Testing needed?** → [TESTING_COMMAND_MENU.md](./TESTING_COMMAND_MENU.md)
- **Finding docs?** → [DOCUMENTATION_INDEX.md](./DOCUMENTATION_INDEX.md)

---

## 🎉 You're Done!

Your bot is now running. Start tracking expenses! 💰

**Next:** Try different transaction types and create your first goal.

