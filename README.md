# Telegram Reminder Bot

A Telegram bot built with [aiogram 3](https://docs.aiogram.dev/) for setting and managing reminders, with support for Jalali (Persian) dates.

## Features
- Natural-language reminder parsing
- Recurring reminders and daily agenda
- Inline keyboard interactions
- Jalali calendar support

## Project structure
```
.
├── handlers/       # Message, callback, and inline handlers
├── keyboards/       # Telegram inline/reply keyboards
├── middlewares/      # aiogram middlewares (e.g. user context)
├── models/         # Data models (user, reminder, tag, attachment, history)
├── services/        # Business logic (user, reminder services)
├── states/          # FSM states
├── utils/          # Helper utilities (jalali dates, reminder utils)
├── tests/          # Unit tests
├── config.py        # Environment-based configuration
├── database.py       # DB setup/connection
├── scheduler.py       # APScheduler jobs for reminders
├── parser.py         # Reminder text parsing logic
└── main.py          # Entry point
```

## Setup

1. Clone the repository and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your values:
   ```bash
   cp .env.example .env
   ```

3. Run the bot:
   ```bash
   python main.py
   ```

## Environment variables

See `.env.example` for the full list, including `TELEGRAM_BOT_TOKEN`, database URL, timezone, and log level.

## Tests

```bash
pytest tests/
```
