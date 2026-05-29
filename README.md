# 💰 Telegram Finance Management Bot

An AI-powered personal finance assistant built with Python. Send natural language messages — English or Hindi — and the bot parses them using Groq AI and saves structured transactions to Google Sheets automatically.

---

## ✨ Features

- 🤖 **AI-powered parsing** — Groq LLaMA 3.3 understands English, Hindi, and Hinglish
- 🔐 **Password protection** — Secure multi-device access with a shared password
- 📊 **Google Sheets sync** — Every transaction saved automatically
- 📅 **Monthly summaries** — Income vs expense breakdown by category
- 📋 **Recent transactions** — View last 10 entries instantly
- 🔄 **Smart mode switching** — Polling locally, webhook on Render (auto-detected)

---

## 📁 Project Structure

```
telegram-finance-bot/
├── bot.py                  # Main bot — handlers, Flask routes, mode switching
├── groq_handler.py         # Groq AI — NLP to structured JSON
├── sheets_handler.py       # Google Sheets read/write
├── auth.py                 # Password verification & session management
├── utils.py                # Message formatting helpers
├── requirements.txt        # Python dependencies
├── render.yaml             # Render.com web service config
├── .env.example            # Environment variable template
├── .gitignore              # Keeps secrets out of Git
└── README.md               # This file
```

---

## 🔧 Step-by-Step Setup

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/telegram-finance-bot.git
cd telegram-finance-bot
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Create Your Telegram Bot

1. Open Telegram → search **@BotFather** → send `/newbot`
2. Follow prompts, copy the **Bot Token** (e.g. `123456789:ABCdef...`)

### 4. Get a Free Groq API Key

1. Visit [https://console.groq.com](https://console.groq.com) → sign up
2. **API Keys → Create API Key** → copy it

### 5. Set Up Google Sheets

#### 5a. Create the Spreadsheet
1. Go to [sheets.google.com](https://sheets.google.com) → create a new spreadsheet
2. Copy the **Spreadsheet ID** from the URL:
   `https://docs.google.com/spreadsheets/d/`**`COPY_THIS_PART`**`/edit`

#### 5b. Create a Service Account
1. Open [Google Cloud Console](https://console.cloud.google.com) → create or select a project
2. **APIs & Services → Enable APIs** → enable:
   - Google Sheets API
   - Google Drive API
3. **APIs & Services → Credentials → Create Credentials → Service Account**
4. Give it any name → **Create and Continue → Done**
5. Click the service account → **Keys → Add Key → JSON** → download
6. Rename the downloaded file to `credentials.json` and place it in the project root

#### 5c. Share Sheet with the Service Account
1. Open `credentials.json`, copy the `client_email` value
2. Open your Google Sheet → **Share** → paste that email → set **Editor** → **Send**

### 6. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
BOT_PASSWORD=YourSecretPassword
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
GOOGLE_CREDENTIALS_PATH=credentials.json
SPREADSHEET_ID=1BxiMVs0XRA5nFMd...
SHEET_NAME=Transactions
WEBHOOK_URL=          # leave blank for local dev
```

### 7. Run Locally

```bash
python bot.py
```

When `WEBHOOK_URL` is blank the bot starts in **polling mode** automatically — no server needed.

---

## 💬 Usage

### Start the Bot
Send `/start` → enter the password when prompted.

### Log a Transaction
Just type naturally:

| Message | Logged as |
|---|---|
| `Spent 500 on petrol` | Expense · ₹500 · Fuel |
| `Received 50000 salary` | Income · ₹50,000 · Salary |
| `1200 rupay grocery mein gaye` | Expense · ₹1,200 · Groceries |
| `Paanch sau ka khana` | Expense · ₹500 · Food & Dining |
| `Teen hazaar freelance mila` | Income · ₹3,000 · Freelance |
| `Paid 800 electricity bill` | Expense · ₹800 · Utilities |

### Commands

| Command | Description |
|---|---|
| `/start` | Start / log in |
| `/recent` | Last 10 transactions |
| `/summary` | Monthly income vs expense summary |
| `/logout` | Log out from current device |
| `/help` | Help message |

---

## 📊 Google Sheets Structure

The bot auto-creates headers on first run:

| Date | Type | Category | Amount | Note | User | Timestamp |
|---|---|---|---|---|---|---|
| 2024-01-15 | expense | Fuel | 500 | Petrol | john | 2024-01-15 14:32:10 |

---

## ☁️ Deploy to Render — Free Web Service

> Render's **Web Service** (free tier) hosts Flask apps with HTTPS.  
> We use **Telegram webhooks** instead of polling so no background worker is needed.

### Step 1 — Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/telegram-finance-bot.git
git push -u origin main
```

> ⚠️ `.env` and `credentials.json` are in `.gitignore` — **never** push them.

### Step 2 — Create a Render Web Service

1. Go to [render.com](https://render.com) → sign up / log in with GitHub
2. Click **New → Web Service**
3. Connect your GitHub repo
4. Configure:

| Field | Value |
|---|---|
| **Name** | `telegram-finance-bot` |
| **Region** | Any (closest to you) |
| **Branch** | `main` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn bot:flask_app --bind 0.0.0.0:$PORT --workers 1 --timeout 120` |
| **Instance Type** | `Free` |

### Step 3 — Add Environment Variables

In the Render dashboard → **Environment** tab → add each variable:

```
TELEGRAM_BOT_TOKEN      → your bot token
BOT_PASSWORD            → your chosen password
GROQ_API_KEY            → your Groq key
GROQ_MODEL              → llama-3.3-70b-versatile
SPREADSHEET_ID          → your sheet ID
SHEET_NAME              → Transactions
GOOGLE_CREDENTIALS_PATH → credentials.json
WEBHOOK_URL             → https://telegram-finance-bot.onrender.com
```

> ⚠️ Set `WEBHOOK_URL` to your **actual Render app URL** (shown at the top of the Render dashboard after deploy). This is what tells the bot to start in webhook mode instead of polling.

### Step 4 — Upload credentials.json as a Secret File

Since `credentials.json` can't go to GitHub, use Render's **Secret Files**:

1. Render dashboard → your service → **Environment** tab
2. Scroll to **Secret Files**
3. Click **Add Secret File**
4. **Filename:** `credentials.json`
5. **Contents:** paste the entire JSON from your local `credentials.json`
6. Save

### Step 5 — Deploy

Click **Create Web Service** — Render builds and deploys automatically (takes ~2 minutes).

### Step 6 — Register the Webhook with Telegram

After deployment, visit this URL **once** in your browser:

```
https://telegram-finance-bot.onrender.com/set_webhook
```

You should see:
```json
{"ok": true, "webhook_url": "https://telegram-finance-bot.onrender.com/webhook"}
```

✅ **Done!** Your bot is now live and free.

---

## 🔁 How Mode Switching Works

| Environment | `WEBHOOK_URL` set? | Mode |
|---|---|---|
| Local (`python bot.py`) | No (blank) | **Polling** — no server needed |
| Render (`gunicorn bot:flask_app`) | Yes | **Webhook** — Flask receives updates |

You never need to change code — just set or unset `WEBHOOK_URL`.

---

## 🔒 Security Notes

- Never commit `.env` or `credentials.json` to Git
- Use a strong `BOT_PASSWORD` (12+ characters)
- The service account only needs **Editor** access to your specific spreadsheet
- Sessions are in-memory — users re-authenticate after a Render cold start (free tier spins down after inactivity)

---

## 🛠️ Customization

**Add categories** — edit the category list in `groq_handler.py` `SYSTEM_PROMPT`

**Change AI model** — update `GROQ_MODEL` in `.env`:
- `llama-3.3-70b-versatile` — best Hindi support (recommended)
- `llama-3.1-8b-instant` — faster, lower latency
- `mixtral-8x7b-32768` — alternative

---

## 🐛 Troubleshooting

| Problem | Fix |
|---|---|
| Bot doesn't respond on Render | Visit `/set_webhook` URL to re-register |
| "WEBHOOK_URL not set" on `/set_webhook` | Add `WEBHOOK_URL` env var in Render dashboard |
| Sheet not updating | Confirm service account has Editor access to the sheet |
| `credentials.json` not found | Add it as a Secret File in Render (see Step 4) |
| Hindi not parsed correctly | Ensure `GROQ_MODEL=llama-3.3-70b-versatile` |
| Bot slow to respond | Free Render tier cold-starts after 15 min inactivity — first message may take ~30s |

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `python-telegram-bot` | Telegram Bot API |
| `flask` | HTTP server for webhook mode |
| `gunicorn` | Production WSGI server (used by Render) |
| `groq` | Groq AI API client |
| `gspread` | Google Sheets API |
| `google-auth` | Google service account auth |
| `python-dotenv` | Load `.env` files |

---

## 📄 License

MIT — free to use, modify, and distribute.
