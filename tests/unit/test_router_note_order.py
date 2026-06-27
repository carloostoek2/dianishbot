"""Router ordering: handle_diana_note before handle_diana_correction."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import state
from handlers.router import process_update


ADMIN_ID = 555003
ADMIN_CHAT_ID = 555003
VIP_CHAT_ID = 777002


@pytest.fixture(autouse=True)
def _reset_state():
    state.awaiting_note.clear()
    state.awaiting_correction.clear()
    yield
    state.awaiting_note.clear()
    state.awaiting_correction.clear()


@pytest.fixture
def admin_user(make_user):
    return make_user(user_id=ADMIN_ID, username="diana_admin", first_name="Diana")


@pytest.fixture
def admin_chat(make_chat):
    return make_chat(chat_id=ADMIN_CHAT_ID)


@pytest.mark.asyncio
async def test_note_handler_before_correction(
    make_mock_update, make_context, admin_user, admin_chat,
):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    state.awaiting_correction[ADMIN_ID] = 99

    update = make_mock_update(
        text="Mi nota manual",
        user=admin_user,
        chat=admin_chat,
    )
    ctx = make_context()
    mock_svc = MagicMock()

    with (
        patch("handlers.router.DIANA_ADMIN_CHAT_ID", ADMIN_CHAT_ID),
        patch("handlers.callbacks.llm_mod.memory_service", mock_svc),
        patch(
            "handlers.router.handle_diana_correction",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_correction,
    ):
        await process_update(update, ctx)

    mock_correction.assert_not_awaited()
    assert ADMIN_ID not in state.awaiting_note


@pytest.mark.asyncio
async def test_slash_command_fallthrough_during_awaiting_note(
    make_mock_update, make_context, admin_user, admin_chat,
):
    state.awaiting_note[ADMIN_ID] = {
        "user_id": VIP_CHAT_ID,
        "username": "testvip",
    }
    update = make_mock_update(
        text="/nota 123 texto",
        user=admin_user,
        chat=admin_chat,
    )
    ctx = make_context()

    with (
        patch("handlers.router.DIANA_ADMIN_CHAT_ID", ADMIN_CHAT_ID),
        patch("handlers.router.auth_users.get_admin_id", return_value=ADMIN_ID),
        patch(
            "handlers.router.auth_users.handle_admin_message",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_admin,
    ):
        await process_update(update, ctx)

    mock_admin.assert_awaited_once()


@pytest.mark.asyncio
async def test_correction_runs_when_only_awaiting_correction(
    make_mock_update, make_context, admin_user, admin_chat,
):
    state.awaiting_correction[ADMIN_ID] = 99
    update = make_mock_update(
        text="Corrección ideal",
        user=admin_user,
        chat=admin_chat,
    )
    ctx = make_context()

    with (
        patch("handlers.router.DIANA_ADMIN_CHAT_ID", ADMIN_CHAT_ID),
        patch(
            "handlers.router.handle_diana_correction",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_correction,
    ):
        await process_update(update, ctx)

    mock_correction.assert_awaited_once()


@pytest.mark.asyncio
async def test_correction_slash_fallthrough_to_admin(
    make_mock_update, make_context, admin_user, admin_chat,
):
    state.awaiting_correction[ADMIN_ID] = 99
    update = make_mock_update(
        text="/nota 123 texto",
        user=admin_user,
        chat=admin_chat,
    )
    ctx = make_context()

    with (
        patch("handlers.router.DIANA_ADMIN_CHAT_ID", ADMIN_CHAT_ID),
        patch("handlers.router.auth_users.get_admin_id", return_value=ADMIN_ID),
        patch(
            "handlers.router.auth_users.handle_admin_message",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_admin,
    ):
        await process_update(update, ctx)

    mock_admin.assert_awaited_once()
    assert ADMIN_ID in state.awaiting_correction