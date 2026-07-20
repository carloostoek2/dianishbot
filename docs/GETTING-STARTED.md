<!-- generated-by: gsd-doc-writer -->
# Getting Started

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | >= 3.13 | Probado con CPython 3.13 / 3.14 |
| pip | Latest | For installing dependencies into a venv |
| Telegram account | — | Diana's account with **Chat Automation** enabled |
| Telegram bot | — | Created via [@BotFather](https://t.me/BotFather) |
| DeepSeek API key | — | For LLM responses (or Anthropic if `LLM_PROVIDER=anthropic`) |

**Python packages** — ver `requirements.txt` (runtime) y `requirements-dev.txt` (tests):

- `python-telegram-bot` >= 21.0 (probado con 22.x)
- `python-dotenv`
- `aiohttp`
- `telethon` (backfill de historial VIP + `extractor.py`)
- `pytest` / `pytest-asyncio` (solo desarrollo)

## Installation steps

1. **Clone the repository**

```bash
git clone <repository-url>
cd diana
```

2. **Create and activate a virtual environment**

```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
# desarrollo / tests:
# pip install -r requirements-dev.txt
```

4. **Configure environment variables**

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```
BOT_TOKEN=your_telegram_bot_token
LLM_PROVIDER=deepseek
DEEPSEEK_KEY=your_deepseek_api_key
```

Opcional: `ANTHROPIC_KEY` si usas `LLM_PROVIDER=anthropic`; `API_ID` / `API_HASH` para Telethon (extractor y backfill).

Asegura que exista `diana_system_prompt.md` en la raíz (persona del bot; no va en git).

5. **Connect Chat Automation**

On Diana's Telegram account:

- Go to **Settings → Chat Automation**
- Connect the bot created in BotFather
- Ensure business messages are routed to the bot

The bot persists the business connection ID to `diana_state.json` on first activation.

## First run

```bash
source venv/bin/activate
python diana.py
```

Expected startup log output includes:

- `DB de entrenamiento lista: diana_training.db`
- `Diana Business Bot v2.0 iniciando...`
- VIP count, observation mode, supervised/autonomous mode, and delay settings

The bot runs long-polling and listens for: `business_connection`, `business_message`, `edited_business_message`, `message`, and `callback_query` updates.

**Seed VIP users:** On first run, IDs in `VIP_USERS_SEED` (defined in `config.py`) are written to `diana_authorized_users.json` if the file does not exist.

**Add more VIPs:** As admin, DM the bot `/usuarios` and forward a user's message to add them to the allowlist.

## Common setup issues

### Missing environment variables

```
Faltan variables de entorno: BOT_TOKEN, DEEPSEEK_KEY. Copia .env.example a .env y configúralas.
```

**Fix:** Create `.env` from `.env.example` and fill in both values.

### Business messages not arriving

**Symptoms:** Bot starts but never logs `ENTRADA` messages.

**Fix:** Verify Chat Automation is enabled on Diana's account and the bot connection is active. Check `diana_business.log` for `Conexión activa` on startup. Restart the bot after enabling the connection.

### `ReadTimeout` or Telegram network errors

**Symptoms:** Intermittent disconnects or timeout errors in logs.

**Fix:** The bot configures extended timeouts (`TG_CONNECT_TIMEOUT=15`, `TG_READ_TIMEOUT=30`) in `config.py` and applies them in `diana.py` via `Application.builder()`. Ensure stable network connectivity. The bot uses `bootstrap_retries=-1` for automatic reconnection.

### User cannot be added via forward

**Symptoms:** Bot replies that it cannot obtain the user ID.

**Fix:** The forwarded user may have **forward privacy** enabled. Ask them to disable it or message the bot directly first so their ID is known.

## Next steps

- [DEVELOPMENT.md](DEVELOPMENT.md) — local development workflow and code conventions
- [TESTING.md](TESTING.md) — current test status and how to add tests
- [CONFIGURATION.md](CONFIGURATION.md) — all environment variables and runtime constants
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design and data flow