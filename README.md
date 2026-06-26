<!-- generated-by: gsd-doc-writer -->
# Diana Business Bot

Telegram Business Chat Automation bot that covers VIP conversations on Diana's account using DeepSeek LLM responses, human-like delivery timing, supervised training, and per-user memory.

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

For the optional chat-history extractor, also install Telethon:

```bash
pip install telethon
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

When `APPROVAL_MODE` is enabled in `config.py`, Diana receives draft previews in her admin DM with **Enviar tal cual** / **Corregir antes** buttons before messages reach VIPs.

**Extract full chat histories for training (bootstrap):**

```bash
# 1. Add API_ID / API_HASH to .env (from https://my.telegram.org)
# 2. pip install telethon
# 3. List chats
python extractor.py list

# 4. Export a specific chat as ready-to-import training data
python extractor.py export --chat 123456789 --format training --import-db

# Formats:
#   raw      → full JSON with every message
#   training → context + diana response (same shape as diana_training.db)
#   pairs    → simple user/diana turns
```

## Project layout

| Path | Purpose |
|------|---------|
| `diana.py` | Entry point — wiring, logging, `Application` setup |
| `config.py` | Environment variables, constants, system prompt |
| `state.py` | In-memory runtime state (history, timers, connections) |
| `auth_users.py` | VIP allowlist and `/usuarios` admin commands |
| `handlers/` | Telegram update routing, business messages, timers, callbacks |
| `services/` | LLM calls, delivery, training DB, user memory |
| `extractor.py` | Standalone Telethon tool for exporting chat histories |
| `.env` | `BOT_TOKEN`, `DEEPSEEK_KEY`, and optional `API_ID` / `API_HASH` |
| `diana_training.db` | SQLite store for few-shot training examples and user memory |

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — system design and data flow
- [Getting Started](docs/GETTING-STARTED.md) — prerequisites and first run
- [Development](docs/DEVELOPMENT.md) — local setup and conventions
- [Testing](docs/TESTING.md) — test status and how to add tests
- [Configuration](docs/CONFIGURATION.md) — environment variables and runtime settings