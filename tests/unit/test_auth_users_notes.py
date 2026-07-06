"""Unit tests for /nota, /notas, /borrar_notas admin commands and VIP forward."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import MessageOrigin

from services.memory import MemoryService

import auth_users


ADMIN_ID = 555002
VIP_ID = 888001


@pytest.fixture(autouse=True)
def _configure_admin(tmp_path):
    users_file = tmp_path / "authorized.json"
    auth_users.configure(users_file=str(users_file), max_users=5, seed_user_ids=[])
    auth_users.set_admin_id(ADMIN_ID)
    yield


@pytest.fixture
def admin_user(make_user):
    return make_user(user_id=ADMIN_ID, username="diana_admin", first_name="Diana")


@pytest.mark.asyncio
async def test_nota_command_saves(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.add_note.return_value = True
    update = make_mock_update(text="/nota 888001 Es muy sensible", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    mock_svc.add_note.assert_called_once_with(888001, "Es muy sensible")


@pytest.mark.asyncio
async def test_nota_usage_error(make_mock_update, make_context, admin_user):
    update = make_mock_update(text="/nota 123", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    update.message.reply_text.assert_awaited_once()
    assert "Uso:" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_notas_lists_profile(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.get_notes.return_value = [
        {"text": "Nota uno", "date": "2026-06-01T12:00:00"},
    ]
    mock_svc.get_facts.return_value = {"name": "Carlos", "notes": "ignored"}
    update = make_mock_update(text=f"/notas {VIP_ID}", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    text = update.message.reply_text.await_args[0][0]
    assert "Notas de Diana:" in text
    assert "Nota uno" in text
    assert "name: Carlos" in text


@pytest.mark.asyncio
async def test_borrar_notas(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.clear_notes.return_value = True
    update = make_mock_update(text=f"/borrar_notas {VIP_ID}", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    mock_svc.clear_notes.assert_called_once_with(VIP_ID)


@pytest.mark.asyncio
async def test_nota_invalid_user_id(make_mock_update, make_context, admin_user):
    update = make_mock_update(text="/nota abc texto", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "numérico" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_nota_memory_unavailable(make_mock_update, make_context, admin_user):
    update = make_mock_update(text="/nota 888001 texto", user=admin_user)

    with patch("services.llm.memory_service", None):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "Memoria no disponible" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_borrar_notas_empty(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.clear_notes.return_value = False
    update = make_mock_update(text=f"/borrar_notas {VIP_ID}", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "No había notas" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_non_admin_ignored(make_mock_update, make_context, make_user):
    update = make_mock_update(
        text="/nota 1 texto",
        user=make_user(user_id=999999),
    )

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is False


@pytest.mark.asyncio
async def test_nota_empty_note_rejected(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.add_note.return_value = False
    update = make_mock_update(text="/nota 888001 \x00\x01", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "vacía" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_notas_memory_unavailable(make_mock_update, make_context, admin_user):
    update = make_mock_update(text=f"/notas {VIP_ID}", user=admin_user)

    with patch("services.llm.memory_service", None):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "Memoria no disponible" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_borrar_notas_memory_unavailable(make_mock_update, make_context, admin_user):
    update = make_mock_update(text=f"/borrar_notas {VIP_ID}", user=admin_user)

    with patch("services.llm.memory_service", None):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "Memoria no disponible" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_notas_usage_error(make_mock_update, make_context, admin_user):
    update = make_mock_update(text="/notas", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "Uso:" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_notas_empty_profile(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.get_notes.return_value = []
    mock_svc.get_facts.return_value = {}
    update = make_mock_update(text=f"/notas {VIP_ID}", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "Sin datos" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_notas_malformed_note_skipped(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.get_notes.return_value = [{"date": "2026-01-01"}]
    mock_svc.get_facts.return_value = {"name": "Ana"}
    update = make_mock_update(text=f"/notas {VIP_ID}", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    text = update.message.reply_text.await_args[0][0]
    assert "name: Ana" in text
    assert "Notas de Diana:" not in text


@pytest.mark.asyncio
async def test_notas_invalid_user_id(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    update = make_mock_update(text="/notas abc", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "inválido" in update.message.reply_text.await_args[0][0].lower()
    mock_svc.get_notes.assert_not_called()


@pytest.mark.asyncio
async def test_notas_non_string_date_coerced(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.get_notes.return_value = [{"text": "ok", "date": 20260101}]
    mock_svc.get_facts.return_value = {}
    update = make_mock_update(text=f"/notas {VIP_ID}", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    text = update.message.reply_text.await_args[0][0]
    assert "[20260101]" in text
    assert "ok" in text


@pytest.mark.asyncio
async def test_notas_non_string_note_text(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.get_notes.return_value = [{"text": 999, "date": "2026-01-01"}]
    mock_svc.get_facts.return_value = {}
    update = make_mock_update(text=f"/notas {VIP_ID}", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    text = update.message.reply_text.await_args[0][0]
    assert "999" in text


@pytest.mark.asyncio
async def test_borrar_notas_usage_error(make_mock_update, make_context, admin_user):
    update = make_mock_update(text="/borrar_notas", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "Uso:" in update.message.reply_text.await_args[0][0]


@pytest.mark.asyncio
async def test_borrar_notas_invalid_user_id(make_mock_update, make_context, admin_user):
    update = make_mock_update(text="/borrar_notas abc", user=admin_user)

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "inválido" in update.message.reply_text.await_args[0][0].lower()


@pytest.mark.asyncio
async def test_nota_takes_precedence_over_forward(
    make_mock_update, make_context, admin_user,
):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.add_note.return_value = True
    update = make_mock_update(text="/nota 888001 texto", user=admin_user)
    update.message.forward_origin = MagicMock()

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    mock_svc.add_note.assert_called_once_with(888001, "texto")


@pytest.mark.asyncio
async def test_nota_persist_error(make_mock_update, make_context, admin_user):
    mock_svc = MagicMock(spec=MemoryService)
    mock_svc.add_note.side_effect = RuntimeError("db locked")
    update = make_mock_update(text="/nota 888001 texto", user=admin_user)

    with patch("services.llm.memory_service", mock_svc):
        result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert "Error" in update.message.reply_text.await_args[0][0]


def _forward_update(make_mock_update, admin_user, *, user_id, username, first_name):
    update = make_mock_update(text=None, user=admin_user)
    origin = MagicMock()
    origin.type = MessageOrigin.USER
    origin.sender_user = MagicMock(id=user_id, username=username, first_name=first_name)
    update.message.forward_origin = origin
    return update


@pytest.mark.asyncio
async def test_forward_registered_user_shows_profile(
    make_mock_update, make_context, admin_user,
):
    auth_users.add_user(VIP_ID, "vip_user", "VIP Name")
    update = _forward_update(
        make_mock_update, admin_user,
        user_id=VIP_ID, username="vip_user", first_name="VIP Name",
    )
    ctx = make_context()

    result = await auth_users.handle_admin_message(update, ctx)

    assert result is True
    update.message.reply_text.assert_not_awaited()
    ctx.bot.send_message.assert_awaited_once()
    text = ctx.bot.send_message.await_args[1]["text"]
    assert "👤 Perfil" in text
    assert f"ID: {VIP_ID}" in text
    assert "Modo respuesta:" in text
    assert ctx.bot.send_message.await_args[1]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_forward_new_user_registers(
    make_mock_update, make_context, admin_user,
):
    new_id = 777001
    update = _forward_update(
        make_mock_update, admin_user,
        user_id=new_id, username="new_vip", first_name="New VIP",
    )

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    assert auth_users.get_user_entry(new_id) is not None
    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args[0][0]
    assert "Agregado:" in text
    assert str(new_id) in text


@pytest.mark.asyncio
async def test_forward_hidden_user_error(make_mock_update, make_context, admin_user):
    update = make_mock_update(text=None, user=admin_user)
    origin = MagicMock()
    origin.type = MessageOrigin.HIDDEN_USER
    update.message.forward_origin = origin

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    update.message.reply_text.assert_awaited_once()
    assert "privacidad" in update.message.reply_text.await_args[0][0].lower()


@pytest.mark.asyncio
async def test_forward_unidentified_origin_error(
    make_mock_update, make_context, admin_user,
):
    update = make_mock_update(text=None, user=admin_user)
    origin = MagicMock()
    origin.type = MessageOrigin.CHANNEL
    update.message.forward_origin = origin

    result = await auth_users.handle_admin_message(update, make_context())

    assert result is True
    update.message.reply_text.assert_awaited_once()
    assert "identificar" in update.message.reply_text.await_args[0][0].lower()