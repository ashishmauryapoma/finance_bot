# 💰 Telegram Finance Bot

A personal expense tracking bot for Telegram with natural language processing, Google Sheets integration, and advanced goal tracking.

[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Status: Active](https://img.shields.io/badge/Status-Active-brightgreen)](https://github.com)

---

## ✨ Features

### 📝 Natural Language Transactions
- Type expenses naturally: `"spent 500 on groceries"`
- Automatic category detection via Groq LLM
- Supports English and Hindi mixed input
- Instant transaction logging to Google Sheets

### 🎯 Multiple Savings Goals
- Create unlimited concurrent goals
- Track progress with visual progress bars
- Set deadlines and daily saving targets
- Auto-detect goal deposits from natural language
- Lock funds when goals complete
- Refund amounts when goals are broken

### 📊 Financial Reports
- **Recent**: View last 10 transactions
- **Summary**: Monthly income/expense breakdown by category
- **Balance**: Net balance + active/completed goals overview
- Real-time calculations from Google Sheets

### 🔐 Secure Access
- Password-protected single-user access
- Session-based authentication
- Secure logout functionality

### 🤖 Smart Command Menu
- Auto-registered command menu in Telegram
- Easy "/" autocomplete with descriptions
- Mobile-friendly menu button support

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.8 or higher
- Telegram Bot Token (from @BotFather)
- Groq API Key (from https://console.groq.com)
- Google Cloud Service Account credentials

### 2. Install
```bash
git clone <repo-url>
cd finance_bot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure
Create `.env` file:
```env
TELEGRAM_BOT_TOKEN=your_bot_token
GROQ_API_KEY=your_groq_key
GOOGLE_SHEETS_CREDENTIALS=./credentials.json
BOT_PASSWORD=your_password
```

### 4. Run
```bash
python bot.py
```

**See [PROJECT_SETUP.md](./PROJECT_SETUP.md) for detailed instructions.**

---

## 📖 Usage Guide

### Transaction Entry
Send any natural language message:

```
User: spent 500 on groceries
Bot: ✅ Transaction Saved!
     💱 Type: 💸 Expense
     📂 Category: Groceries
     💵 Amount: ₹500.00

User: earned 5000 salary today
Bot: ✅ Transaction Saved!
     💱 Type: 💰 Income
     📂 Category: Salary
     💵 Amount: ₹5000.00
```

### Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Login to bot | `/start` |
| `/recent` | Last 10 transactions | `/recent` |
| `/summary` | Monthly report | `/summary` |
| `/balance` | Net balance & goals | `/balance` |
| `/help` | Help & all commands | `/help` |
| `/logout` | Logout | `/logout` |

### Goal Management

**Create Goal:**
```
/goal set Trip | 50000 | 2026-12-31
✅ Goal created!
🎯 Trip
💰 Saved: ₹0.00 / ₹50,000.00
```

**Add to Goal:**
```
/goal add Trip 2000
✅ ₹2,000.00 deposited & logged
```

**View Goal:**
```
/goal view Trip
Shows detailed progress and daily saving target
```

**List All Goals:**
```
/goal list
Shows all active and completed goals with summaries
```

**Break Goal (refund):**
```
/goal break Trip
Asks for confirmation, then refunds saved amount
```

### Natural Goal Detection
Users can also use natural language:
```
saved 1000 for trip
→ Bot asks: Which goal? [Trip] [Other Goal]
→ User taps [Trip]
→ ₹1000 added to Trip goal
```

---

## 🏗️ Architecture

### Technology Stack
- **Bot Framework**: python-telegram-bot 21.6
- **LLM**: Groq (llama-3.3-70b-versatile)
- **Data Store**: Google Sheets + gspread
- **Web Server**: Flask (for webhooks)
- **Async Runtime**: asyncio

### Data Flow
```
User Message
    ↓
Telegram Bot API
    ↓
bot.py (MessageHandler)
    ↓
Goal Detection? → Groq LLM → detect_goal_deposit()
    ↓ (if goal)
Goal Operations → sheets_handler → Google Sheets
    ↓ (if not goal)
Transaction Parsing → Groq LLM → extract_transaction()
    ↓
Append to Sheet → Google Sheets
    ↓
Format Response → goal_handler/utils
    ↓
Send Message → Telegram Bot API → User
```

### File Structure
```
finance_bot/
├── bot.py                          # Main bot logic
├── groq_handler.py                 # NLP & transaction parsing
├── sheets_handler.py               # Google Sheets operations
├── auth.py                         # Authentication
├── goal_handler.py                 # Goal formatting
├── utils.py                        # Utilities
├── requirements.txt                # Dependencies
├── .env.example                    # Environment template
├── credentials.json                # Google credentials (add yourself)
├── render.yaml                     # Render.com deployment
├── PROJECT_SETUP.md                # Setup guide
├── COMMAND_MENU_IMPLEMENTATION.md  # Feature documentation
└── README.md                       # This file
```

---

## 🔧 Configuration

### Environment Variables
```env
# Required
TELEGRAM_BOT_TOKEN              # Bot token from @BotFather
GROQ_API_KEY                    # API key from console.groq.com
GOOGLE_SHEETS_CREDENTIALS       # Path to credentials.json

# Optional
GROQ_MODEL                      # Default: llama-3.3-70b-versatile
BOT_PASSWORD                    # Password for bot access
WEBHOOK_URL                     # For production deployment
PORT                            # Default: 8080
```

### Categories
**100+ predefined expense categories:**
- Rent, Bills, Groceries, Food, Transport, Medical, etc.

**40+ income categories:**
- Salary, Freelancing, Bonus, Interest, Dividends, etc.

Edit in `groq_handler.py` to customize.

---

## 🚢 Deployment

### Development (Polling)
```bash
python bot.py
```
- Easy local testing
- Requires terminal open
- Suitable for development

### Production (Webhook)
```bash
WEBHOOK_URL=https://your-domain.com python bot.py
```

**Render.com Example:**
1. Push to GitHub
2. Create Render Web Service
3. Set environment variables
4. Deploy (WEBHOOK_URL auto-configured)

See [PROJECT_SETUP.md](./PROJECT_SETUP.md#deployment) for detailed instructions.

---

## 📊 Performance

- **Response Time**: <2 seconds average
- **Memory Usage**: ~100 MB
- **CPU Usage**: Minimal (async)
- **Concurrent Users**: Unlimited
- **Supported Users**: Single-user (can modify for multi-user)

---

## 🔒 Security

✓ Password-protected access
✓ Google service account authentication
✓ HTTPS for webhook connections
✓ No sensitive data in logs
✓ Async/non-blocking operations
✓ Input validation & sanitization

**Note:** Never commit `.env` or `credentials.json` to git.

---

## 🐛 Troubleshooting

### Bot doesn't start
```bash
# Check Python version
python --version  # Should be 3.8+

# Check dependencies
pip install -r requirements.txt
```

### "Token not set" error
- Verify `.env` file exists
- Check `TELEGRAM_BOT_TOKEN` is set correctly
- Restart bot

### Bot doesn't respond
- Check bot is running (`python bot.py`)
- Verify token with `/setMyCommands` test
- Check user is authenticated (`/start` first)
- View logs for errors

### Google Sheets errors
- Verify `credentials.json` path
- Check sheet exists and is shared
- Verify service account email has editor access

**See [PROJECT_SETUP.md](./PROJECT_SETUP.md#troubleshooting) for more solutions.**

---

## 📝 Recent Changes

### v1.2 (Current)
- ✅ Telegram command menu registration
- ✅ Auto-discovered commands with descriptions
- ✅ Mobile-friendly menu button support
- ✅ Improved command routing

### v1.1
- ✅ Multiple concurrent goals support
- ✅ Goal completion locking
- ✅ Natural goal detection
- ✅ Goal refund on deletion

### v1.0
- ✅ Basic transaction tracking
- ✅ Natural language parsing
- ✅ Google Sheets integration
- ✅ Monthly reports

---

## 🎨 Sample Output

### Balance Report
```
🟢 Net Balance: ₹45,320.50
────────────────────────────────
📅 This Month:
   📥 Income: ₹35,000.00
   📤 Expenses: ₹12,350.50
   Net: ₹22,649.50

✅ Active Goals (2):
   • Trip: ₹12,000/₹50,000 (24%) — ₹38,000 to go
   • Car Fund: ₹8,500/₹200,000 (4%) — ₹191,500 to go
   💰 Total in Active: ₹20,500.00

✨ Completed Goals (1):
   🔒 Wedding: ₹5,000.00 (locked)
   🔐 Total Locked: ₹5,000.00
```

### Goal Progress
```
🎯 Trip
━━━━━━━━━━━━━━━━━━━━━━━━━━
💰 Saved: ₹12,000.00 / ₹50,000.00
📊 Progress: [████████░░] 24.0%
📅 Deadline: 2026-12-31 (125 days left)
💡 Need: ₹400/day to reach goal
━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🤝 Contributing

Feel free to:
- Fork the project
- Add new features
- Fix bugs
- Improve documentation
- Submit pull requests

---

## 📄 License

MIT License - See LICENSE file for details

---

## 🙏 Credits

- **Telegram Bot API** - python-telegram-bot
- **LLM** - Groq (fast inference)
- **Data** - Google Sheets API
- **Deployment** - Render.com

---

## 📞 Support

For issues or questions:
1. Check [PROJECT_SETUP.md](./PROJECT_SETUP.md)
2. Review code comments
3. Check logs: `python bot.py`
4. Test components individually

---

## 🎯 Roadmap

- [ ] Multi-user support
- [ ] Budget alerts
- [ ] Recurring transactions
- [ ] Export to CSV/PDF
- [ ] Notifications/reminders
- [ ] Mobile app
- [ ] Web dashboard
- [ ] Category customization UI

---

**Happy tracking! 💚**

Created with ❤️ for personal finance management.
