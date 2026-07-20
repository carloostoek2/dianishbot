<!-- generated-by: gsd-doc-writer -->
# Configuration

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BOT_TOKEN` | **Yes** | — | Telegram bot token from [@BotFather](https://t.me/BotFather). Loaded via `python-dotenv` at startup. Startup fails if missing. |
| `LLM_PROVIDER` | No | `deepseek` | `deepseek` o `anthropic`. Define qué API key es obligatoria al arrancar. |
| `DEEPSEEK_KEY` | **Yes*** | — | DeepSeek API key. Obligatoria si `LLM_PROVIDER=deepseek` (default). |
| `DEEPSEEK_MODEL` | No | `deepseek-v4-pro` | Modelo DeepSeek (también configurable en runtime vía menú admin). |
| `ANTHROPIC_KEY` | **Yes*** | — | Anthropic API key. Obligatoria si `LLM_PROVIDER=anthropic`. |
| `ANTHROPIC_MODEL` | No | `claude-haiku-4-5-20251001` | Modelo Anthropic. |
| `API_ID` | No | — | Telegram API ID for `extractor.py` / backfill. Get from [my.telegram.org](https://my.telegram.org). |
| `API_HASH` | No | — | Telegram API hash for `extractor.py` / backfill. |
| `TELEGRAM_API_ID` | No | — | Alias for `API_ID` accepted by `extractor.py`. |
| `TELEGRAM_API_HASH` | No | — | Alias for `API_HASH` accepted by `extractor.py`. |
| `DIANA_SYSTEM_PROMPT_FILE` | No | `diana_system_prompt.md` | Ruta al system prompt en disco. |

\* Solo se exige la key del proveedor activo.

Create `.env` from the template:

```bash
cp .env.example .env
```

The template in `.env.example` documents `BOT_TOKEN`, `DEEPSEEK_KEY`, `API_ID`, and `API_HASH` with placeholder values.

## Config file format

Beyond environment variables, runtime behavior is controlled by **constants in `config.py`**. There is no external config file — edit `config.py` to change these values.

### API and model

| Constant | Value | Description |
|----------|-------|-------------|
| `DEEPSEEK_URL` | `https://api.deepseek.com/v1/chat/completions` | DeepSeek API endpoint |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | Model identifier sent in API requests |

### Auth and state files

| Constant | Value | Description |
|----------|-------|-------------|
| `AUTH_USERS_FILE` | `diana_authorized_users.json` | VIP allowlist persistence path |
| `AUTH_USERS_MAX` | `10` | Maximum authorized VIP users |
| `STATE_FILE` | `diana_state.json` | Business connection state file |
| `VIP_USERS_SEED` | Set of user IDs | Seeded into allowlist on first run if JSON file is missing |

### Timing and behavior

| Constant | Value | Description |
|----------|-------|-------------|
| `RESPONSE_DELAY_MIN` | `1` | Min delay (minutes) before auto-reply in autonomous mode |
| `RESPONSE_DELAY_MAX` | `8` | Max delay (minutes) — actual delay is random in range |
| `SILENCE_MINUTES` | `2` | Wait time in supervised (`APPROVAL_MODE`) mode |
| `MAX_HISTORY` | `50` | Messages sent to LLM as conversation context |
| `MAX_STORED_HISTORY` | `50` | Messages persisted per chat in SQLite (`chat_history`); trim on append/seed |
| `BACKFILL_INTERVAL_SEC` | `3600` | Asyncio scheduler interval — one VIP per hour |
| `BACKFILL_MSG_LIMIT` | `100` | Telethon fetch limit per VIP (trimmed to `MAX_STORED_HISTORY` on seed) |
| `BACKFILL_QUEUE_FILE` | `diana_backfill_queue.json` | Pending VIP backfill queue (gitignored) |
| `MAX_FEW_SHOTS` | `3` | Approved examples injected into system prompt |
| `CONFIDENCE_THRESHOLD` | `70` | Responses below this % trigger admin notification (autonomous mode) |
| `APPROVAL_MODE` | `True` | `True` = supervised (Diana approves drafts); `False` = autonomous |
| `OBSERVE_UNAUTHORIZED` | `True` | Log and learn from non-authorized chats without auto-replying |
| `SKIP_OBSERVED_TOPICS` | `{"contenido", "precio", "acceso", "horarios", "presentacion"}` | Topics excluded from observed (unauthorized) training examples |

### Telegram network timeouts

| Constant | Value (seconds) |
|----------|-----------------|
| `TG_CONNECT_TIMEOUT` | `15.0` |
| `TG_READ_TIMEOUT` | `30.0` |
| `TG_WRITE_TIMEOUT` | `30.0` |
| `TG_POOL_TIMEOUT` | `5.0` |
| `TG_POLL_TIMEOUT` | `30` |

### Admin and logging

| Constant | Description |
|----------|-------------|
| `ADMIN_USER_ID` | Diana's Telegram user ID for admin DM commands |
| `DIANA_ADMIN_CHAT_ID` | Same as admin ID — receives approval drafts and training notifications |
| `LOG_FILE` | `diana_business.log` |
| `ESCALATE_FILE` | `diana_escalaciones.txt` |
| `DB_FILE` | `diana_training.db` |

### Topic classification

`TOPIC_MAP` in `config.py` maps topic labels to keyword lists used by `guess_topic()` in `services/llm.py` for few-shot selection. `ESCALATE_KEYWORDS` triggers immediate escalation without auto-reply.

## Required vs optional settings

**Startup will fail** if `BOT_TOKEN` or the active LLM key is absent:

```python
# diana.py main() — raises SystemExit
provider = llm_settings.get_provider()
llm_key_name = "ANTHROPIC_KEY" if provider == "anthropic" else "DEEPSEEK_KEY"
missing = [name for name, val in (
    ("BOT_TOKEN", BOT_TOKEN),
    (llm_key_name, llm_key_val),
) if not val]
```

Also fails if `diana_system_prompt.md` (or `DIANA_SYSTEM_PROMPT_FILE`) is missing/empty.

All other settings have defaults defined in `config.py` or are created at runtime (SQLite DB, JSON state files).

`extractor.py` requires `API_ID` and `API_HASH` at runtime but not for the main bot.

## Runtime data files

These files are created automatically and listed in `.gitignore`:

| File | Created by | Purpose |
|------|------------|---------|
| `diana_authorized_users.json` | `auth_users._save()` | VIP allowlist |
| `diana_state.json` | `state._save_connections_state()` | Active business connection IDs |
| `diana_training.db` | `services/training.init_db()` + `MemoryService` | Training examples and user memory |
| `diana_business.log` | `logging` in `diana.py` | Application logs |
| `diana_escalaciones.txt` | `handlers/business.log_escalation()` | Escalation audit trail |
| `diana_session.session` | `extractor.py` / backfill scheduler (Telethon) | User-session for chat export and VIP history backfill |
| `diana_backfill_queue.json` | `services/history_backfill.py` | Pending VIP IDs for hourly history backfill |

## Per-environment overrides

The project does not use `.env.development` / `.env.production` split files. Configuration differences between environments are handled by:

1. Different `.env` files on each deployment host (not committed).
2. Editing constants in `config.py` for mode changes (`APPROVAL_MODE`, delays, thresholds).

<!-- VERIFY: Production deployment host paths and process manager (systemd, screen, etc.) are not defined in the repository. -->