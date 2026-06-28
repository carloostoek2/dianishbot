"""Unit tests for /sandbox admin commands."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import state
from services import sandbox
from services.memory import MemoryService

import auth_users


_REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_ID = 555002
VIP_CHAT_ID = 888001


@pytest.fixture
def profiles_file(tmp_path):
    path = tmp_path / "sandbox_profiles.json"
    src = _REPO_ROOT / "diana_sandbox_profiles.json"
    path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _configure(profiles_file, tmp_path):
    users_file = tmp_path / "authorized.json"
    auth_users.configure(
        users_file=str(users_file),
        max_users=5,
        seed_user_ids=[VIP_CHAT_ID],
        admin_id=ADMIN_ID,
    )
    auth_users.set_admin_id(ADMIN_ID)
    sandbox.configure(profiles_file=str(profiles_file))
    sandbox._active.clear()
    sandbox._focus_chat_id = None
    sandbox._next_draft_id = 0
    state.history.clear()
    yield
    sandbox._active.clear()
    sandbox._focus_chat_id = None
    state.history.clear()


@pytest.fixture
def admin_user(make_user):
    return make_user(user_id=ADMIN_ID, username="diana_admin", first_name="Diana")


@pytest.mark.asyncio
async def test_sandbox_on_activates(make_mock_update, make_context, admin_user):
    update = make_mock_update(text=f"/sandbox on {VIP_CHAT_ID}", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert sandbox.is_active(VIP_CHAT_ID)
    reply = update.message.reply_text.await_args[0][0]
    assert str(VIP_CHAT_ID) in reply
    assert "nuevo" in reply


@pytest.mark.asyncio
async def test_sandbox_off_deactivates(make_mock_update, make_context, admin_user):
    sandbox.activate(VIP_CHAT_ID)
    state.history[VIP_CHAT_ID] = [{"role": "user", "content": "hola"}]
    update = make_mock_update(text=f"/sandbox off {VIP_CHAT_ID}", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert not sandbox.is_active(VIP_CHAT_ID)
    assert VIP_CHAT_ID not in state.history


@pytest.mark.asyncio
async def test_sandbox_perfil_sets_focus_profile(make_mock_update, make_context, admin_user):
    sandbox.activate(VIP_CHAT_ID)
    update = make_mock_update(text="/sandbox perfil cercano", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert sandbox.get_profile(VIP_CHAT_ID) == "cercano"


@pytest.mark.asyncio
async def test_sandbox_perfil_no_focus_errors(make_mock_update, make_context, admin_user):
    update = make_mock_update(text="/sandbox perfil cercano", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "Error:" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_sandbox_perfiles_lists_six(make_mock_update, make_context, admin_user):
    update = make_mock_update(text="/sandbox perfiles", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    reply = update.message.reply_text.await_args[0][0]
    assert reply.count(" — ") >= 6


@pytest.mark.asyncio
async def test_sandbox_estado_shows_active(make_mock_update, make_context, admin_user):
    sandbox.activate(VIP_CHAT_ID, profile="intenso")
    update = make_mock_update(text="/sandbox estado", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    reply = update.message.reply_text.await_args[0][0]
    assert str(VIP_CHAT_ID) in reply
    assert "intenso" in reply


@pytest.mark.asyncio
async def test_sandbox_reset_clears_history(make_mock_update, make_context, admin_user):
    sandbox.activate(VIP_CHAT_ID)
    state.history[VIP_CHAT_ID] = [{"role": "user", "content": "hola"}]
    update = make_mock_update(text="/sandbox reset", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert VIP_CHAT_ID not in state.history
    assert sandbox.is_active(VIP_CHAT_ID)


@pytest.mark.asyncio
async def test_sandbox_non_admin_rejected(make_mock_update, make_context, make_user):
    update = make_mock_update(
        text=f"/sandbox on {VIP_CHAT_ID}",
        user=make_user(user_id=999999),
    )

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is False
    update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_nota_blocked_for_sandbox_chat(make_mock_update, make_context, admin_user):
    sandbox.activate(VIP_CHAT_ID)
    update = make_mock_update(
        text=f"/nota {VIP_CHAT_ID} texto de prueba",
        user=admin_user,
    )

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "sandbox" in update.message.reply_text.await_args[0][0].lower()


@pytest.mark.asyncio
async def test_sandbox_invalid_chat_id(make_mock_update, make_context, admin_user):
    update = make_mock_update(text="/sandbox on abc", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "numérico" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_sandbox_on_warns_authorized_vip(make_mock_update, make_context, admin_user):
    update = make_mock_update(text=f"/sandbox on {VIP_CHAT_ID}", user=admin_user)

    await auth_users.handle_admin_message(update, make_context())

    reply = update.message.reply_text.await_args[0][0]
    assert "entregan al usuario real" in reply


@pytest.mark.asyncio
async def test_sandbox_off_not_active_message(make_mock_update, make_context, admin_user):
    update = make_mock_update(text=f"/sandbox off {VIP_CHAT_ID}", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "no tenía sandbox activo" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_handle_admin_note_blocked_in_sandbox(make_mock_update, make_context, admin_user):
    sandbox.activate(VIP_CHAT_ID)
    state.awaiting_admin_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_update(text="Nota admin bloqueada", user=admin_user)

    with patch("services.llm.memory_service", MagicMock(spec=MemoryService)):
        result = await auth_users.handle_admin_note(update, make_context())

    assert result is True
    assert ADMIN_ID not in state.awaiting_admin_note
    assert "sandbox" in update.message.reply_text.await_args[0][0].lower()


@pytest.mark.asyncio
async def test_start_admin_note_capture_blocked_in_sandbox(admin_user):
    sandbox.activate(VIP_CHAT_ID)
    query = MagicMock()
    query.from_user = admin_user
    query.answer = AsyncMock()

    await auth_users._start_admin_note_capture(query, VIP_CHAT_ID)

    query.answer.assert_awaited_once()
    assert "sandbox" in query.answer.await_args[0][0].lower()
    assert ADMIN_ID not in state.awaiting_admin_note


@pytest.mark.asyncio
async def test_borrar_notas_blocked_in_sandbox(make_mock_update, make_context, admin_user):
    sandbox.activate(VIP_CHAT_ID)
    update = make_mock_update(text=f"/borrar_notas {VIP_CHAT_ID}", user=admin_user)

    with patch("services.llm.memory_service", MagicMock(spec=MemoryService)):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "sandbox" in update.message.reply_text.await_args[0][0].lower()


@pytest.mark.asyncio
async def test_clear_notes_callback_blocked_in_sandbox(admin_user):
    sandbox.activate(VIP_CHAT_ID)
    query = MagicMock()
    query.data = f"au:notes_clear_ok:{VIP_CHAT_ID}"
    query.from_user = admin_user
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.edit_message_text = AsyncMock()
    query.message.reply_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    mock_svc = MagicMock(spec=MemoryService)
    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_callback(update, AsyncMock())

    assert result is True
    mock_svc.clear_notes.assert_not_called()
    query.answer.assert_awaited_once()
    assert "sandbox" in query.answer.await_args[0][0].lower()


@pytest.mark.asyncio
async def test_notes_clear_confirm_blocked_in_sandbox(admin_user):
    sandbox.activate(VIP_CHAT_ID)
    query = MagicMock()
    query.data = f"au:notes_clear:{VIP_CHAT_ID}"
    query.from_user = admin_user
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.edit_message_text = AsyncMock()
    query.message.reply_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.get_notes.return_value = [{"text": "nota", "date": "2026-01-01"}]
    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_callback(update, AsyncMock())

    assert result is True
    query.answer.assert_awaited_once()
    assert "sandbox" in query.answer.await_args[0][0].lower()
    query.message.edit_message_text.assert_not_called()
    query.message.reply_text.assert_not_called()