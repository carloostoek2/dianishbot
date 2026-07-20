<!-- generated-by: gsd-doc-writer; updated: documentador sistema-notas 2026-06-27 -->
# Testing

## Test framework and setup

**Status:** pytest suite present — **103 tests**, all passing.

| Check | Result |
|-------|--------|
| `tests/` directory | `tests/unit/` + `tests/conftest.py` |
| Framework | pytest + pytest-asyncio |
| `pytest.ini`, `pyproject.toml` test config | Not configured (defaults) |
| CI workflow with test steps | Not found |

**Dependencies:** `pip install -r requirements-dev.txt` (incluye `pytest` y `pytest-asyncio`).

**Fixtures:** `tests/conftest.py` — PTB 22.8-compatible mocks (`make_mock_update`, `make_mock_callback_update`, `make_context`, `test_db`, `admin_user`).

## Running tests

```bash
source venv/bin/activate
pip install -r requirements-dev.txt
PYTHONPATH=. pytest tests/ -v
```

```bash
# Quick run
PYTHONPATH=. pytest tests/ -q
```

```bash
# Sistema de Notas slice (68 tests)
PYTHONPATH=. pytest tests/unit/test_memory_notes.py \
  tests/unit/test_callbacks_note.py \
  tests/unit/test_auth_users_notes.py \
  tests/unit/test_router_note_order.py -v
```

```bash
# Single file
PYTHONPATH=. pytest tests/unit/test_auth_users_notes.py -v
```

```bash
# Single test
PYTHONPATH=. pytest tests/unit/test_memory_notes.py::test_add_note_returns_true_on_success -v
```

## Test inventory (103 total)

| File | Tests | Scope |
|------|-------|-------|
| `tests/unit/test_memory_notes.py` | 22 | `MemoryService` notes CRUD, `_persist_notes`, `get_context_block`, sanitization |
| `tests/unit/test_callbacks_note.py` | 21 | 📝 Nota button, `handle_diana_note`, `/cancelar_nota`, mutual exclusion |
| `tests/unit/test_auth_users_notes.py` | 21 | `/nota`, `/notas`, `/borrar_notas` admin commands |
| `tests/unit/test_router_note_order.py` | 4 | Router precedence: note handler before correction |
| `tests/unit/test_llm_pure.py` | 12 | `guess_topic`, `_parse_confidence`, prompt helpers |
| `tests/unit/test_llm_retry.py` | 5 | LLM retry behavior |
| `tests/unit/test_llm_raw_call.py` | 5 | `raw_call` HTTP mocking |
| `tests/unit/test_llm_failures_db.py` | 3 | Failure logging / DB |
| `tests/unit/test_business_logic.py` | 5 | `needs_escalation()` keyword detection |
| `tests/unit/test_auth_users.py` | 3 | Allowlist CRUD |
| `tests/unit/test_timer_auto_reply.py` | 2 | `auto_reply` delivery path |

## Writing new tests

**File naming:** `tests/test_<module>.py` or `tests/unit/test_<module>.py`

**Conventions:**
- Pure logic: no Telegram mocks needed (`test_business_logic.py`, `test_memory_notes.py` service layer).
- Handlers / admin commands: use `make_mock_update`, `make_context`, `admin_user` from `conftest.py`.
- Callback flows: use `make_mock_callback_update`.
- Async tests: `@pytest.mark.asyncio`.

**Example skeleton:**

```python
# tests/unit/test_auth_users.py
import json
import auth_users
from pathlib import Path

def test_is_authorized(tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"users": {"123": {"id": 123}}}))
    auth_users.configure(users_file=str(users_file), max_users=10)
    assert auth_users.is_authorized(123) is True
    assert auth_users.is_authorized(999) is False
```

**Notes-specific patterns** (phase 04):
- Test `/notas` before `/nota ` routing — prefix collision guard.
- Mock `llm_mod.memory_service` for admin command tests.
- Assert `awaiting_note` ↔ `awaiting_correction` mutual exclusion on `a:note` / `a:fix`.
- Use `test_db` fixture for `_persist_notes` bypass of `set_fact` 300-char cap.

## Coverage requirements

No coverage threshold configured.

## CI integration

No CI/CD pipeline detected. Run `PYTHONPATH=. pytest tests/` locally before merging.

Manual verification checklist (Telegram test bot):

1. Bot starts without missing-env errors.
2. `/usuarios` lists and modifies the allowlist.
3. `/nota <id> <text>`, `/notas <id>`, `/borrar_notas <id>` work in admin DM.
4. 📝 **Nota** on approval draft captures note; `/cancelar_nota` preserves pending draft.
5. Authorized VIP messages trigger timer → LLM → delivery (or approval flow); notes appear in context.
6. Escalation keywords skip auto-reply and log to `diana_escalaciones.txt`.
7. Callback buttons (approve, fix, note, rate, delete user) respond correctly.