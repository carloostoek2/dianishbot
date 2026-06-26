<!-- generated-by: gsd-doc-writer -->
# Architecture

## System overview

Diana Business Bot v2.0 is a modular Python application that uses Telegram's **Business Connection / Chat Automation** API to respond on Diana's behalf in VIP chats. Incoming business messages are routed through a central update handler, authorized against a JSON allowlist, deferred via cancellable asyncio timers, enriched with few-shot examples from SQLite and per-user memory facts, and sent to the DeepSeek API. Responses are delivered with human-like timing (read receipts, typing indicators, randomized pauses). In supervised mode, Diana approves or corrects drafts before they reach users.

**Primary inputs:** Telegram business messages, admin DMs, callback queries  
**Primary outputs:** Business messages to VIP chats, admin notifications, SQLite training records, user memory facts  
**Style:** Async event loop with layered handlers/services, timer-based deferred responses, and human-in-the-loop approval

## Component diagram

```text
┌─────────────────────────────────────────────────────────────┐
│                   Telegram (Business Mode)                   │
│   VIP chats ←→ Diana's account via Chat Automation          │
├──────────────────┬──────────────────┬───────────────────────┤
│  VIP messages    │  Diana manual    │  Admin DM (/usuarios) │
│  (authorized)    │  replies         │  callbacks            │
└────────┬─────────┴────────┬─────────┴──────────┬────────────┘
         │                  │                     │
         ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│           handlers/router.py — process_update()              │
├──────────────────┬──────────────────┬───────────────────────┤
│ handlers/        │ auth_users.py    │ handlers/callbacks.py │
│ business.py      │                  │ handle_callback       │
│ timer.py         │                  │ handle_diana_correction│
└────────┬─────────┴──────────────────┴──────────┬────────────┘
         │                                        │
         ▼                                        ▼
┌─────────────────────┐              ┌─────────────────────────┐
│ auto_reply()        │              │ Admin approval / rating │
│ services/llm.py     │              │ notify_diana_*          │
│ services/delivery.py│              │                         │
└────────┬────────────┘              └────────────┬────────────┘
         │                                        │
         ▼                                        ▼
┌─────────────────────┐              ┌─────────────────────────┐
│ DeepSeek API (LLM)  │              │ services/training.py    │
│ JSON response       │              │ services/memory.py      │
└────────┬────────────┘              └─────────────────────────┘
         │
         ▼
┌─────────────────────┐
│ deliver_vip_response│
│ read → pause → type │
│ → send_message      │
└─────────────────────┘
```

## Data flow

A typical VIP message flows through the system as follows:

1. **Ingress** — Telegram delivers a `business_message` update. `process_update()` in `handlers/router.py` routes it to `_handle_business_message()` in `handlers/business.py`.
2. **Authorization** — The sender is resolved via `_resolve_vip_id()`. `auth_users.is_authorized()` checks `diana_authorized_users.json`.
3. **Escalation check** — `needs_escalation()` scans for keywords (payments, crisis, etc.). Matches are logged to `diana_escalaciones.txt` and skip auto-reply; Diana receives an escalation DM.
4. **Timer scheduling** — A cancellable `asyncio` task (`auto_reply` in `handlers/timer.py`) is scheduled. In supervised mode, delay is `SILENCE_MINUTES`; otherwise a random range between `RESPONSE_DELAY_MIN` and `RESPONSE_DELAY_MAX`.
5. **LLM call** — `get_diana_response()` in `services/llm.py` builds a system prompt from `DIANA_SYSTEM_PROMPT`, injects user memory via `MemoryService.get_context_block()`, adds few-shots from `get_few_shots()`, and posts to DeepSeek. The model returns JSON: `response`, `confidence`, `topic`.
6. **Approval gate** — If `APPROVAL_MODE` is true, `notify_diana_approval()` sends a draft to Diana's admin DM with inline approve/fix buttons. In autonomous mode, low-confidence responses trigger `notify_diana()` instead.
7. **Delivery** — `deliver_vip_response()` in `services/delivery.py` runs the human-like chain: `mark_as_read` → pause → `simulate_typing` → `send_message` with `business_connection_id`.
8. **Training & memory** — Examples are saved via `save_example()`. After successful delivery, `schedule_memory_extract()` runs background fact extraction into `user_memory`. Diana rates or corrects via callback handlers; reviewed examples feed future few-shots.

## Key abstractions

| Abstraction | Description | Location |
|-------------|-------------|----------|
| `process_update()` | Central router for all Telegram update types | `handlers/router.py` |
| `_handle_business_message()` | VIP message ingestion, timer management | `handlers/business.py` |
| `auto_reply()` | Deferred reply task with generation tracking | `handlers/timer.py` |
| `get_diana_response()` | DeepSeek LLM call with memory and few-shot injection | `services/llm.py` |
| `raw_call()` | Low-level DeepSeek HTTP request | `services/llm.py` |
| `deliver_vip_response()` | Human-like message delivery chain | `services/delivery.py` |
| `MemoryService` | Per-user fact storage and background extraction | `services/memory.py` |
| `init_db()` / `save_example()` | SQLite training persistence | `services/training.py` |
| `auth_users.configure()` | Allowlist module initialization | `auth_users.py` |
| `auth_users.is_authorized()` | VIP authorization check | `auth_users.py` |
| `DIANA_SYSTEM_PROMPT` | Persona, voice rules, escalation policy | `config.py` |

## Directory structure rationale

The project uses a **modular flat layout** — application code is grouped by concern at the repository root without a `src/` package.

```
diana/
├── diana.py              # Entry point — wiring, logging, polling
├── config.py             # Env vars, constants, system prompt, escalation keywords
├── state.py              # In-memory dicts (history, timers, pending approval)
├── auth_users.py         # VIP allowlist CRUD and admin commands
├── handlers/
│   ├── router.py         # Update dispatch
│   ├── business.py       # Business message handling, escalation
│   ├── timer.py          # Deferred auto_reply tasks
│   └── callbacks.py      # Approval, rating, correction callbacks
├── services/
│   ├── llm.py            # DeepSeek API integration
│   ├── delivery.py       # Read receipts, typing, send
│   ├── training.py       # SQLite examples and few-shots
│   └── memory.py         # Per-user fact extraction and storage
├── extractor.py          # Standalone Telethon export tool
├── docs/                 # Project documentation
├── diana_authorized_users.json   # Runtime: VIP allowlist (gitignored)
├── diana_state.json              # Runtime: business connection IDs (gitignored)
├── diana_training.db             # Runtime: SQLite training + memory (gitignored)
└── venv/                         # Python virtual environment (not committed)
```

**Why modular?** v2.0 splits the former monolithic `diana.py` into handlers (Telegram I/O) and services (LLM, persistence, delivery) so each concern can be tested and extended independently. `diana.py` remains the composition root that wires shared state (`db`, `memory_service`) into modules at startup.

## Callback routing

Inline keyboard callbacks use prefixed `callback_data` values:

| Prefix | Purpose |
|--------|---------|
| `a:` | Approval mode — approve or fix draft before sending |
| `t:` | Training feedback — rate bot responses (autonomous mode) |
| `au:` | Authorized user management — delete from allowlist |

## Persistence model

| Store | Format | Managed by |
|-------|--------|------------|
| VIP allowlist | `diana_authorized_users.json` | `auth_users.py` |
| Business connections | `diana_state.json` | `state.py` (`_save_connections_state`) |
| Training examples | `diana_training.db` — `examples` table | `services/training.py` |
| User memory facts | `diana_training.db` — `user_memory` table | `services/memory.py` |
| Escalation audit | `diana_escalaciones.txt` | `handlers/business.py` (`log_escalation`) |
| Application log | `diana_business.log` | `diana.py` logging setup |