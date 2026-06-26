<!-- generated-by: gsd-doc-writer -->
# Diana Business Bot

Telegram Business Chat Automation bot that covers VIP conversations on Diana's account using DeepSeek LLM responses, human-like delivery timing, and a supervised training loop.

## Installation

```bash
git clone <repository-url>
cd diana
python3 -m venv venv
source venv/bin/activate
pip install "python-telegram-bot>=21.0" python-dotenv aiohttp
cp .env.example .env
# Edit .env with your BOT_TOKEN and DEEPSEEK_KEY
```

## Quick start

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather) and copy the token into `.env`.
2. Obtain a DeepSeek API key and set `DEEPSEEK_KEY` in `.env`.
3. Enable **Chat Automation** on Diana's Telegram account and connect the bot.
4. Run the bot:

```bash
source venv/bin/activate
python diana.py
```

5. As admin, DM the bot `/usuarios` to manage the VIP allowlist.

## Usage examples

**Run the bot (long-polling):**

```bash
python diana.py
```

**Manage authorized VIP users (admin DM to bot):**

```
/usuarios
```

Forward a user's message to the bot to add them; use inline buttons to remove users.

**Approve or correct draft responses (supervised mode):**

When `APPROVAL_MODE` is enabled in `diana.py`, Diana receives draft previews in her admin DM with **Enviar tal cual** / **Corregir antes** buttons before messages reach VIPs.

**Extract full chat histories for training (bootstrap):**

```bash
# 1. Add your API_ID / API_HASH to .env (from https://my.telegram.org)
# 2. List chats
python extractor.py list

# 3. Export a specific chat as ready-to-import training data
python extractor.py export -c 123456789 -f training --import-db

# Formats:
#   raw      → full JSON with every message
#   training → context + diana response (same shape as diana_training.db)
#   pairs    → simple user/diana turns
```

## Project layout

| File | Purpose |
|------|---------|
| `diana.py` | Main bot — routing, LLM, timers, delivery, training |
| `auth_users.py` | VIP allowlist and `/usuarios` admin commands |
| `extractor.py` | Standalone Telethon tool: export full chat histories → training examples |
| `.env` | `BOT_TOKEN` and `DEEPSEEK_KEY` secrets (+ API_ID / API_HASH for extractor) |
| `diana_training.db` | SQLite store for few-shot training examples |
| `diana_authorized_users.json` | Persisted VIP allowlist |

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — system design and data flow
- [Getting Started](docs/GETTING-STARTED.md) — prerequisites and first run
- [Development](docs/DEVELOPMENT.md) — local setup and conventions
- [Testing](docs/TESTING.md) — test status and how to add tests
- [Configuration](docs/CONFIGURATION.md) — environment variables and runtime settings