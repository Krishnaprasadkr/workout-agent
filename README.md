# 🏋️ Daily Workout Agent — Setup Guide

Your personal AI workout agent. Runs every day at 4 PM IST, sends your workout plan to Telegram, logs history to Google Sheets, and progressively overloads your weights automatically.

---

## What you need (all free)

| Tool | Purpose |
|---|---|
| GitHub account | Hosts your code + runs the agent daily |
| Google account | Gemini API (free) + Google Sheets (storage) |
| Telegram account | Receives your daily workout |

---

## Step 1 — Get your Gemini API Key (5 min)

1. Go to https://aistudio.google.com/app/apikey
2. Click **Create API Key**
3. Copy and save the key — looks like `AIzaSy...`

---

## Step 2 — Create your Telegram Bot (3 min)

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Give it a name like `My Workout Agent`
4. Give it a username like `myworkout_agent_bot`
5. BotFather will send you a **token** — looks like `7123456789:AAF...` — save it
6. Now get your Chat ID:
   - Search for **@userinfobot** on Telegram
   - Send it `/start`
   - It will reply with your **Chat ID** — a number like `987654321`

---

## Step 3 — Set up Google Sheets (5 min)

1. Go to https://sheets.google.com and create a new spreadsheet
2. Rename the first sheet tab to: `WorkoutHistory`
3. Copy the **Spreadsheet ID** from the URL:
   - URL looks like: `https://docs.google.com/spreadsheets/d/SPREADSHEET_ID_IS_HERE/edit`
   - Copy the long ID between `/d/` and `/edit`
4. Now create a Service Account to let the agent write to your sheet:
   - Go to https://console.cloud.google.com
   - Create a new project (name it anything)
   - Go to **APIs & Services → Enable APIs** → search **Google Sheets API** → Enable it
   - Go to **APIs & Services → Credentials → Create Credentials → Service Account**
   - Name it `workout-agent`, click Create
   - Click the service account email → **Keys tab → Add Key → JSON**
   - Download the JSON file — this is your `GOOGLE_CREDENTIALS_JSON`
5. Share your Google Sheet with the service account email:
   - Open your spreadsheet → Share button
   - Paste the service account email (looks like `workout-agent@your-project.iam.gserviceaccount.com`)
   - Give it **Editor** access

---

## Step 4 — Push code to GitHub (5 min)

1. Go to https://github.com and create a new **private** repository named `workout-agent`
2. Upload all these files to the repo:
   - `workout_agent.py`
   - `gemini_helper.py`
   - `sheets_helper.py`
   - `telegram_helper.py`
   - `requirements.txt`
   - `.github/workflows/daily.yml`

---

## Step 5 — Add secrets to GitHub (5 min)

1. In your GitHub repo, go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret** and add each of these:

| Secret Name | Value |
|---|---|
| `GEMINI_API_KEY` | Your Gemini API key from Step 1 |
| `TELEGRAM_BOT_TOKEN` | Your bot token from Step 2 |
| `TELEGRAM_CHAT_ID` | Your chat ID from Step 2 |
| `SPREADSHEET_ID` | Your sheet ID from Step 3 |
| `GOOGLE_CREDENTIALS_JSON` | Paste the full contents of the JSON file from Step 3 |

---

## Step 6 — Initialize sheet headers (1 min)

Run this once to create the header row in your Google Sheet:

```bash
pip install -r requirements.txt

# Set env vars temporarily (Windows PowerShell)
$env:GOOGLE_CREDENTIALS_JSON = (Get-Content service-account.json -Raw)
$env:SPREADSHEET_ID = "your_sheet_id_here"

python sheets_helper.py
```

---

## Step 7 — Test it manually

In your GitHub repo, go to **Actions → Daily Workout Agent → Run workflow**.

You should receive a Telegram message within 30 seconds! 🎉

---

## How progressive overload works

- The agent counts how many times each split has been done from Sheets history
- Every **2 sessions** of the same split, weights increase:
  - Compound exercises (Bench, Squat, Deadlift, Row, Press): **+2.5kg**
  - Isolation exercises (Curls, Flies, Laterals): **+1kg**
- This happens automatically — you don't need to do anything

---

## Changing your workout time

Edit `.github/workflows/daily.yml` — change the cron line:

```yaml
- cron: "30 10 * * *"   # 10:30 UTC = 4:00 PM IST
```

Use https://crontab.guru to calculate the right UTC time for your timezone.

---

## Weekly Summary

Every **Sunday**, after the daily workout message, you'll receive a weekly summary with:
- All sessions completed that week
- Total volume per muscle group
- Progressive overload progress
- Recommendations for next week

---

## Troubleshooting

**Agent didn't run?** → Check Actions tab in GitHub for error logs

**Telegram message not received?** → Verify BOT_TOKEN and CHAT_ID secrets

**Google Sheets error?** → Make sure the sheet tab is named exactly `WorkoutHistory` and the service account has Editor access

**Gemini error?** → Check your API key at https://aistudio.google.com/app/apikey
