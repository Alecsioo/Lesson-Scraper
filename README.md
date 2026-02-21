# 🕷️ Generic Lesson Scraper

A configurable Playwright-based scraper that logs into a web platform, navigates through a course timeline, and downloads lesson data as JSON files — organised by chapter.

---

## 📋 Prerequisites

Make sure the following are installed before running the script:

- [Python 3.10+](https://www.python.org/downloads/)
- [pip](https://pip.pypa.io/en/stable/)

Then install the required Python packages:

```bash
pip install playwright python-dotenv
playwright install chromium
```

---

## ⚙️ Environment Setup

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```ini
# Credentials
EMAIL=you@example.com
PASSWORD=yourpassword

# URLs
LOGIN_URL=https://example.com/login
TIMELINE_URL=https://example.com/dashboard
BASE_URL=https://example.com

# Auth detection
LOGIN_URL_FRAGMENT=/login

# Selectors
SELECTOR_TIMELINE=#timeline-content
SELECTOR_LOGIN_EMAIL=#login-form-email
SELECTOR_LOGIN_PASSWORD=#login-form-password
SELECTOR_LOGIN_BUTTON=button[type='submit']
SELECTOR_CHAPTER=section
SELECTOR_CHAPTER_TITLE=h3
SELECTOR_LESSON_CARD=[data-testid='lesson_card']
SELECTOR_LESSON_TITLE=[data-testid='dialog_level_title']
SELECTOR_BTN_CHECKPOINT=button:has-text("Start quiz")
SELECTOR_BTN_LESSON=button:has-text("Let's go!"), button:has-text("Restart")

# API
API_RESPONSE_PATTERN=api.example.com/v2/component/objective_

# Skip lesson types (comma-separated, matched case-insensitively)
SKIP_TYPES=SPEAKING PRACTICE,AI CONVERSATIONS

# Output
OUTPUT_DIR=lessons
SESSION_FILE=session.json
```

> ⚠️ Never commit your `.env` or `session.json` — both are listed in `.gitignore`.

---

## 🚀 Running the Script

```bash
python scraper.py
```

---

## 🔐 Authentication

The script logs in automatically using the credentials in your `.env`.

On the **first run**, a browser window will open and submit your credentials. If the platform requires a **CAPTCHA**, you'll need to solve it manually — the script will wait until you do. Once logged in, the session cookies are saved to `session.json` and reused on all subsequent runs, so manual intervention should only be needed once.

If the session expires, the script detects this automatically, deletes the stale `session.json`, and prompts a fresh login.

---

## 🛠️ How It Works

1. **Session check** — navigates to the timeline URL and waits for the timeline selector. If it doesn't appear within 10 seconds, the session is considered invalid and a fresh login is performed.

2. **Chapter discovery** — scans the timeline for all chapter sections using the configured selectors, creating a subdirectory for each one under `OUTPUT_DIR/`.

3. **Lesson iteration** — for each chapter, the script iterates through every lesson card. Lesson types listed in `SKIP_TYPES` (e.g. speaking practice, AI conversations) are skipped automatically.

4. **JSON capture** — each lesson card is clicked, the start button is triggered, and the script intercepts the API response matching `API_RESPONSE_PATTERN`. The JSON payload is saved to the corresponding chapter subdirectory.

5. **Output structure** — files are save
