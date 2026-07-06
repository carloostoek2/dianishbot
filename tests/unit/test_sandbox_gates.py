"""Tests for sandbox write gates across handlers."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import auth_users
import state
from handlers import business, callbacks, timer as timer_mod
from services import sandbox


_REPO_ROOT = Path(__file__).resolve().parents[2]
VIP_CHAT_ID = 777001
ADMIN_ID = 555001


@pytest.fixture
def profiles_file(tmp_path):
    path = tmp_path / "sandbox_profiles.json"
    src = _REPO_ROOT / "diana_sandbox_profiles.json"
    path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _reset_sandbox_and_state(profiles_file, tmp_path):
    users_file = tmp_path / "authorized.json"
    auth_users.configure(
        users_file=str(users_file), max_users=5, seed_user_ids=[], admin_id=ADMIN_ID,
    )
    auth_users.set_admin_id(ADMIN_ID)
    sandbox.configure(profiles_file=str(profiles_file))
    sandbox._active.clear()
    sandbox._focus_chat_id = None
    sandbox._next_draft_id = 0
    state.history.clear()
    state.reply_gen.clear()
    state.timers.clear()
    state.timer_schedule.clear()
    state.pending_approval.clear()
    state.chat_bc.clear()
    state.pending_msg.clear()
    state.chat_meta.clear()
    state.awaiting_note.clear()
    state.awaiting_correction.clear()
    yield
    sandbox._active.clear()
    sandbox._focus_chat_id = None
    sandbox._next_draft_id = 0
    state.history.clear()
    state.reply_gen.clear()
    state.timers.clear()
    state.timer_schedule.clear()
    state.pending_approval.clear()
    state.chat_bc.clear()
    state.pending_msg.clear()
    state.chat_meta.clear()
    state.awaiting_note.clear()
    state.awaiting_correction.clear()


@pytest.fixture
def admin_user(make_user):
    return make_user(user_id=ADMIN_ID, username="diana_admin", first_name="Diana")


@pytest.fixture
def pending_entry():
    return {
        "chat_id": VIP_CHAT_ID,
        "bc_id": "bc_test",
        "username": "testvip",
        "gen": 1,
        "variants": [{"response": "hola", "confidence": 90, "topic": "general"}],
        "selected": 0,
        "regenerating": False,
    }


@pytest.mark.asyncio
async def test_auto_reply_sandbox_skips_save_example(in_memory_training_db):
    sandbox.activate(VIP_CHAT_ID)
    chat_id = VIP_CHAT_ID
    gen = 1
    state.reply_gen[chat_id] = gen
    state.history[chat_id] = [{"role": "user", "content": "hola"}]
    llm_json = '{"response": "hey", "confidence": 85, "topic": "saludo"}'

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("services.llm.raw_call", new_callable=AsyncMock, return_value=(llm_json, None, None)),
        patch("handlers.timer.notify_diana_approval", new_callable=AsyncMock) as mock_notify,
        patch("handlers.timer.save_example") as mock_save,
    ):
        await timer_mod.auto_reply(AsyncMock(), chat_id, "vip", "bc_test", gen)

    mock_save.assert_not_called()
    assert len(state.pending_approval) == 1
    ex_id = next(iter(state.pending_approval))
    assert ex_id < 0
    mock_notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_reply_sandbox_skips_save_llm_failure(in_memory_training_db):
    sandbox.activate(VIP_CHAT_ID)
    chat_id = VIP_CHAT_ID
    gen = 1
    state.reply_gen[chat_id] = gen
    state.history[chat_id] = [{"role": "user", "content": "hola"}]

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("services.llm.raw_call", new_callable=AsyncMock, return_value=(None, "error_http_api", "HTTP 503")),
        patch("handlers.timer.save_llm_failure") as mock_save_fail,
        patch("handlers.timer.notify_diana_llm_failure", new_callable=AsyncMock) as mock_notify,
    ):
        await timer_mod.auto_reply(AsyncMock(), chat_id, "vip", "bc_test", gen)

    mock_save_fail.assert_not_called()
    mock_notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_reply_sandbox_still_notifies_approval(in_memory_training_db):
    sandbox.activate(VIP_CHAT_ID)
    chat_id = VIP_CHAT_ID
    gen = 1
    state.reply_gen[chat_id] = gen
    state.history[chat_id] = [{"role": "user", "content": "hola"}]
    llm_json = '{"response": "hey", "confidence": 85, "topic": "saludo"}'

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("services.llm.raw_call", new_callable=AsyncMock, return_value=(llm_json, None, None)),
        patch("handlers.timer.notify_diana_approval", new_callable=AsyncMock) as mock_notify,
    ):
        await timer_mod.auto_reply(AsyncMock(), chat_id, "vip", "bc_test", gen)

    mock_notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_sandbox_skips_update_rating(
    make_mock_callback_update, make_context, pending_entry, admin_user,
):
    sandbox.activate(VIP_CHAT_ID)
    ex_id = -1
    state.pending_approval[ex_id] = pending_entry.copy()
    state.reply_gen[VIP_CHAT_ID] = 1
    update = make_mock_callback_update(data=f"a:approve:{ex_id}", user=admin_user)

    with (
        patch("handlers.callbacks.deliver_vip_response", new_callable=AsyncMock, return_value=True),
        patch("handlers.callbacks.update_rating") as mock_rating,
        patch("handlers.callbacks.schedule_memory_extract") as mock_extract,
    ):
        await callbacks.handle_callback(update, make_context())

    mock_rating.assert_not_called()
    mock_extract.assert_not_called()


@pytest.mark.asyncio
async def test_approve_sandbox_skips_memory_extract(
    make_mock_callback_update, make_context, pending_entry, admin_user,
):
    sandbox.activate(VIP_CHAT_ID)
    ex_id = -2
    state.pending_approval[ex_id] = pending_entry.copy()
    state.reply_gen[VIP_CHAT_ID] = 1
    update = make_mock_callback_update(data=f"a:approve:{ex_id}", user=admin_user)

    with (
        patch("handlers.callbacks.deliver_vip_response", new_callable=AsyncMock, return_value=True),
        patch("handlers.callbacks.schedule_memory_extract") as mock_extract,
    ):
        await callbacks.handle_callback(update, make_context())

    mock_extract.assert_not_called()


@pytest.mark.asyncio
async def test_a_note_blocked_in_sandbox(
    make_mock_callback_update, make_context, pending_entry, admin_user,
):
    sandbox.activate(VIP_CHAT_ID)
    ex_id = -3
    state.pending_approval[ex_id] = pending_entry.copy()
    update = make_mock_callback_update(data=f"a:note:{ex_id}", user=admin_user)

    await callbacks.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited_once_with("Nota deshabilitada en sandbox")
    assert ADMIN_ID not in state.awaiting_note


def test_approval_keyboard_no_nota_in_sandbox():
    sandbox.activate(VIP_CHAT_ID)
    markup = callbacks._build_approval_keyboard(-1, VIP_CHAT_ID)
    callback_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "a:note:-1" not in callback_data
    assert "a:approve:-1" in callback_data


def test_log_escalation_skipped_in_sandbox(tmp_path, monkeypatch):
    escalate_file = tmp_path / "escalaciones.txt"
    monkeypatch.setattr(business, "ESCALATE_FILE", str(escalate_file))
    sandbox.activate(VIP_CHAT_ID)
    business.log_escalation(
        999, "vip", "test", [{"role": "user", "content": "hola"}], chat_id=VIP_CHAT_ID,
    )
    assert not escalate_file.exists()


def test_runtime_snapshot_excludes_sandbox_chat():
    sandbox.activate(VIP_CHAT_ID)
    state.history[VIP_CHAT_ID] = [{"role": "user", "content": "hola"}]
    state.timer_schedule[VIP_CHAT_ID] = {
        "username": "vip",
        "bc_id": "bc_test",
        "gen": 1,
        "fire_at": "2026-06-28T12:00:00",
    }
    snapshot = state._build_runtime_snapshot()
    assert "777001" not in snapshot.get("history", {})
    assert len(snapshot.get("timers", [])) == 0


def test_runtime_snapshot_excludes_sandbox_pending_approval(pending_entry):
    sandbox.activate(VIP_CHAT_ID)
    state.pending_approval[-1] = pending_entry.copy()
    snapshot = state._build_runtime_snapshot()
    assert "-1" not in snapshot.get("pending_approval", {})
    assert snapshot.get("pending_approval") == {}


@pytest.mark.asyncio
async def test_handle_diana_note_blocked_in_sandbox(
    make_mock_update, make_context, admin_user,
):
    sandbox.activate(VIP_CHAT_ID)
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_update(text="Nota que no debe guardarse", user=admin_user)

    with patch("handlers.callbacks.llm_mod.memory_service") as mock_svc:
        result = await callbacks.handle_diana_note(update, make_context())

    assert result is True
    assert ADMIN_ID not in state.awaiting_note
    mock_svc.add_note.assert_not_called()
    assert "sandbox" in update.message.reply_text.await_args[0][0].lower()


@pytest.mark.asyncio
async def test_t_good_synthetic_id_no_persist(make_mock_callback_update, make_context, admin_user):
    update = make_mock_callback_update(data="t:good:-1", user=admin_user)

    with patch("handlers.callbacks.update_rating") as mock_rating:
        await callbacks.handle_callback(update, make_context())

    mock_rating.assert_not_called()
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "sin persistencia" in update.callback_query.edit_message_text.await_args[0][0].lower()


@pytest.mark.asyncio
async def test_save_observed_example_skipped_in_sandbox(monkeypatch):
    sandbox.activate(500)
    monkeypatch.setattr(business, "OBSERVE_UNAUTHORIZED", True)
    state.connections["bc_test"] = ADMIN_ID
    state.chat_meta[500] = {"vip_id": 999, "username": "observed"}
    state.history[500] = [{"role": "user", "content": "pregunta"}]

    msg = AsyncMock()
    msg.business_connection_id = "bc_test"
    msg.chat.id = 500
    msg.text = "respuesta manual"
    msg.caption = None
    msg.from_user.id = ADMIN_ID
    msg.from_user.username = "diana"
    msg.from_user.first_name = "Diana"
    msg.message_id = 1

    context = AsyncMock()

    with patch("handlers.business.save_observed_example") as mock_save:
        await business._handle_business_message(msg, context, edited=False)

    mock_save.assert_not_called()


def test_format_approval_text_sandbox_header(pending_entry):
    sandbox.activate(VIP_CHAT_ID, profile="cercano")
    text = callbacks._format_approval_text(
        "testvip", [{"role": "user", "content": "hola"}], pending_entry,
    )
    assert "🧪 SANDBOX — perfil: cercano" in text


@pytest.mark.asyncio
async def test_escalate_still_notifies_in_sandbox(tmp_path, monkeypatch):
    escalate_file = tmp_path / "escalaciones.txt"
    monkeypatch.setattr(business, "ESCALATE_FILE", str(escalate_file))
    sandbox.activate(VIP_CHAT_ID)
    with patch(
        "handlers.business.notify_diana_escalation", new_callable=AsyncMock,
    ) as mock_notify:
        await business.escalate_to_diana(
            AsyncMock(),
            user_id=999,
            username="vip",
            chat_id=VIP_CHAT_ID,
            bc_id="bc_test",
            source="keyword",
            reason="test",
            trigger_text="hola",
            context=[{"role": "user", "content": "hola"}],
        )
    mock_notify.assert_awaited_once()
    assert not escalate_file.exists()


def test_log_escalation_uses_chat_id_not_vip_id(tmp_path, monkeypatch):
    """Gate on chat_id — vip_id distinto no debe escribir si chat está en sandbox."""
    escalate_file = tmp_path / "escalaciones.txt"
    monkeypatch.setattr(business, "ESCALATE_FILE", str(escalate_file))
    sandbox.activate(500)
    business.log_escalation(
        999, "vip", "test", [{"role": "user", "content": "hola"}], chat_id=500,
    )
    assert not escalate_file.exists()
    sandbox.deactivate(500)
    business.log_escalation(
        999, "vip", "test", [{"role": "user", "content": "hola"}], chat_id=500,
    )
    assert escalate_file.exists()


@pytest.mark.asyncio
async def test_handle_diana_correction_sandbox_skips_persist(
    make_mock_update, make_context, pending_entry, admin_user,
):
    sandbox.activate(VIP_CHAT_ID)
    ex_id = -5
    state.pending_approval[ex_id] = pending_entry.copy()
    state.reply_gen[VIP_CHAT_ID] = 1
    state.awaiting_correction[ADMIN_ID] = ex_id
    update = make_mock_update(text="correccion sandbox", user=admin_user)

    with (
        patch("handlers.callbacks.deliver_vip_response", new_callable=AsyncMock, return_value=True),
        patch("handlers.callbacks.update_rating") as mock_rating,
        patch("handlers.callbacks.schedule_memory_extract") as mock_extract,
    ):
        await callbacks.handle_diana_correction(update, make_context())

    mock_rating.assert_not_called()
    mock_extract.assert_not_called()
    assert "sin persistencia" in update.message.reply_text.await_args[0][0].lower()


@pytest.mark.asyncio
async def test_approve_sandbox_still_delivers(
    make_mock_callback_update, make_context, pending_entry, admin_user,
):
    sandbox.activate(VIP_CHAT_ID)
    ex_id = -6
    state.pending_approval[ex_id] = pending_entry.copy()
    state.reply_gen[VIP_CHAT_ID] = 1
    update = make_mock_callback_update(data=f"a:approve:{ex_id}", user=admin_user)

    with patch(
        "handlers.callbacks.deliver_vip_response", new_callable=AsyncMock, return_value=True,
    ) as mock_deliver:
        await callbacks.handle_callback(update, make_context())

    mock_deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_approve_non_admin_rejected(
    make_mock_callback_update, make_context, pending_entry, make_user,
):
    ex_id = -7
    state.pending_approval[ex_id] = pending_entry.copy()
    state.reply_gen[VIP_CHAT_ID] = 1
    outsider = make_user(user_id=999888, username="outsider")
    update = make_mock_callback_update(data=f"a:approve:{ex_id}", user=outsider)

    with patch(
        "handlers.callbacks.deliver_vip_response", new_callable=AsyncMock,
    ) as mock_deliver:
        await callbacks.handle_callback(update, make_context())

    mock_deliver.assert_not_called()
    update.callback_query.answer.assert_awaited_once_with("No autorizado")