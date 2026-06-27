"""Unit tests for approval-draft note button and handle_diana_note."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.memory import MemoryService

import state
from handlers.callbacks import (
    handle_callback,
    handle_diana_correction,
    handle_diana_note,
    notify_diana,
    notify_diana_approval,
)


ADMIN_ID = 555001
VIP_CHAT_ID = 777001


@pytest.fixture(autouse=True)
def _reset_state():
    state.awaiting_note.clear()
    state.awaiting_correction.clear()
    state.pending_approval.clear()
    yield
    state.awaiting_note.clear()
    state.awaiting_correction.clear()
    state.pending_approval.clear()


@pytest.fixture
def admin_user(make_user):
    return make_user(user_id=ADMIN_ID, username="diana_admin", first_name="Diana")


@pytest.fixture
def pending_entry():
    return {
        "chat_id": VIP_CHAT_ID,
        "bc_id": "bc_test",
        "username": "testvip",
        "response": "hola",
        "gen": 1,
    }


@pytest.mark.asyncio
async def test_a_note_sets_awaiting_note(
    make_mock_callback_update, make_context, pending_entry, admin_user,
):
    ex_id = 42
    state.pending_approval[ex_id] = pending_entry.copy()
    update = make_mock_callback_update(data=f"a:note:{ex_id}", user=admin_user)

    await handle_callback(update, make_context())

    assert ADMIN_ID in state.awaiting_note
    assert state.awaiting_note[ADMIN_ID]["user_id"] == VIP_CHAT_ID
    assert ex_id in state.pending_approval


@pytest.mark.asyncio
async def test_a_note_clears_awaiting_correction(
    make_mock_callback_update, make_context, pending_entry, admin_user,
):
    ex_id = 43
    state.pending_approval[ex_id] = pending_entry.copy()
    state.awaiting_correction[ADMIN_ID] = ex_id
    update = make_mock_callback_update(data=f"a:note:{ex_id}", user=admin_user)

    await handle_callback(update, make_context())

    assert ADMIN_ID not in state.awaiting_correction
    assert ADMIN_ID in state.awaiting_note


@pytest.mark.asyncio
async def test_a_note_expired_draft(make_mock_callback_update, make_context, admin_user):
    update = make_mock_callback_update(data="a:note:999", user=admin_user)

    await handle_callback(update, make_context())

    update.callback_query.edit_message_text.assert_awaited_once()
    assert "expiró" in update.callback_query.edit_message_text.await_args[0][0]


@pytest.mark.asyncio
async def test_handle_diana_note_saves(make_mock_update, make_context, admin_user):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.add_note.return_value = True
    update = make_mock_update(text="Es muy sensible", user=admin_user)

    with patch("handlers.callbacks.llm_mod.memory_service", mock_svc):
        result = await handle_diana_note(update, make_context())

    assert result is True
    mock_svc.add_note.assert_called_once_with(VIP_CHAT_ID, "Es muy sensible")
    assert ADMIN_ID not in state.awaiting_note


@pytest.mark.asyncio
async def test_cancelar_nota_preserves_pending(
    make_mock_update, make_context, pending_entry, admin_user,
):
    ex_id = 44
    state.pending_approval[ex_id] = pending_entry.copy()
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_update(text="/cancelar_nota", user=admin_user)

    result = await handle_diana_note(update, make_context())

    assert result is True
    assert ex_id in state.pending_approval
    assert ADMIN_ID not in state.awaiting_note


@pytest.mark.asyncio
async def test_notify_diana_no_note_button():
    bot = AsyncMock()
    with patch("handlers.callbacks.DIANA_ADMIN_CHAT_ID", 12345):
        await notify_diana(
            bot,
            example_id=8,
            username="testvip",
            context=[{"role": "user", "content": "hola"}],
            response="respuesta",
            confidence=40,
            topic="general",
        )
    markup = bot.send_message.await_args.kwargs["reply_markup"]
    callback_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "a:note" not in "".join(callback_data)
    assert all(d.startswith("t:") for d in callback_data)


@pytest.mark.asyncio
async def test_notify_diana_approval_has_note_button():
    bot = AsyncMock()
    with patch("handlers.callbacks.DIANA_ADMIN_CHAT_ID", 12345):
        await notify_diana_approval(
            bot,
            example_id=7,
            username="testvip",
            context=[{"role": "user", "content": "hola"}],
            response="respuesta",
            confidence=90,
            topic="general",
        )
    bot.send_message.assert_awaited_once()
    markup = bot.send_message.await_args.kwargs["reply_markup"]
    callback_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "a:note:7" in callback_data
    assert len(callback_data) == 3


@pytest.mark.asyncio
async def test_handle_diana_note_memory_unavailable(
    make_mock_update, make_context, admin_user,
):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_update(text="Nota sin memoria", user=admin_user)

    with patch("handlers.callbacks.llm_mod.memory_service", None):
        result = await handle_diana_note(update, make_context())

    assert result is True
    update.message.reply_text.assert_awaited_once()
    assert "Memoria no disponible" in update.message.reply_text.await_args[0][0]
    assert ADMIN_ID in state.awaiting_note


@pytest.mark.asyncio
async def test_t_fix_clears_awaiting_note(make_mock_callback_update, make_context, admin_user):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_callback_update(data="t:fix:88", user=admin_user)

    await handle_callback(update, make_context())

    assert ADMIN_ID not in state.awaiting_note
    assert state.awaiting_correction[ADMIN_ID] == 88


@pytest.mark.asyncio
async def test_a_fix_clears_awaiting_note(
    make_mock_callback_update, make_context, pending_entry, admin_user,
):
    ex_id = 45
    state.pending_approval[ex_id] = pending_entry.copy()
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_callback_update(data=f"a:fix:{ex_id}", user=admin_user)

    await handle_callback(update, make_context())

    assert ADMIN_ID not in state.awaiting_note
    assert state.awaiting_correction[ADMIN_ID] == ex_id


@pytest.mark.asyncio
async def test_a_approve_clears_awaiting_note(
    make_mock_callback_update, make_context, pending_entry, admin_user,
):
    ex_id = 46
    state.pending_approval[ex_id] = pending_entry.copy()
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_callback_update(data=f"a:approve:{ex_id}", user=admin_user)

    with (
        patch(
            "handlers.callbacks.deliver_vip_response",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("handlers.callbacks.update_rating"),
        patch("handlers.callbacks.schedule_memory_extract"),
    ):
        await handle_callback(update, make_context())

    assert ADMIN_ID not in state.awaiting_note


@pytest.mark.asyncio
async def test_t_good_clears_awaiting_note(make_mock_callback_update, make_context, admin_user):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_callback_update(data="t:good:77", user=admin_user)

    with patch("handlers.callbacks.update_rating"):
        await handle_callback(update, make_context())

    assert ADMIN_ID not in state.awaiting_note


@pytest.mark.asyncio
async def test_t_bad_clears_awaiting_note(make_mock_callback_update, make_context, admin_user):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_callback_update(data="t:bad:78", user=admin_user)

    with patch("handlers.callbacks.update_rating"):
        await handle_callback(update, make_context())

    assert ADMIN_ID not in state.awaiting_note


@pytest.mark.asyncio
async def test_handle_diana_note_not_awaiting_returns_false(
    make_mock_update, make_context, admin_user,
):
    update = make_mock_update(text="texto", user=admin_user)
    assert await handle_diana_note(update, make_context()) is False


@pytest.mark.asyncio
async def test_handle_diana_note_no_text_returns_false(make_context, admin_user):
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = None
    update.message.from_user = admin_user
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    assert await handle_diana_note(update, make_context()) is False


@pytest.mark.asyncio
async def test_handle_diana_note_whitespace_keeps_state(
    make_mock_update, make_context, admin_user,
):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.add_note.return_value = False
    update = make_mock_update(text="   ", user=admin_user)

    with patch("handlers.callbacks.llm_mod.memory_service", mock_svc):
        result = await handle_diana_note(update, make_context())

    assert result is True
    assert ADMIN_ID in state.awaiting_note
    assert "vacía" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_handle_diana_note_slash_command_fallthrough(
    make_mock_update, make_context, admin_user,
):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_update(text="/notas 123", user=admin_user)

    result = await handle_diana_note(update, make_context())

    assert result is False
    assert ADMIN_ID in state.awaiting_note


@pytest.mark.asyncio
async def test_cancelar_nota_with_bot_suffix(make_mock_update, make_context, admin_user):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_update(text="/cancelar_nota@DianaBot", user=admin_user)

    result = await handle_diana_note(update, make_context())

    assert result is True
    assert ADMIN_ID not in state.awaiting_note


@pytest.mark.asyncio
async def test_handle_diana_note_persist_error_keeps_state(
    make_mock_update, make_context, admin_user,
):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.add_note.side_effect = RuntimeError("db locked")
    update = make_mock_update(text="Nota válida", user=admin_user)

    with patch("handlers.callbacks.llm_mod.memory_service", mock_svc):
        result = await handle_diana_note(update, make_context())

    assert result is True
    assert ADMIN_ID in state.awaiting_note
    assert "Error" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_handle_diana_note_no_message_returns_false(make_context):
    update = MagicMock()
    update.message = None
    assert await handle_diana_note(update, make_context()) is False


@pytest.mark.asyncio
async def test_handle_diana_correction_slash_fallthrough(
    make_mock_update, make_context, admin_user,
):
    state.awaiting_correction[ADMIN_ID] = 99
    update = make_mock_update(text="/notas 123", user=admin_user)

    result = await handle_diana_correction(update, make_context())

    assert result is False
    assert ADMIN_ID in state.awaiting_correction