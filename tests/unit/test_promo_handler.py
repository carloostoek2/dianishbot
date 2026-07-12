"""Handler intercept tests for non-VIP promo-info autoreply (WU3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import auth_users
import state
from config import NON_VIP_PROMO_TRIGGER
from handlers import business

NON_VIP_CHAT = 6001
NON_VIP_SENDER = 6001
VIP_ID = 7001
VIP_CHAT = 7001
ADMIN_ID = 1
BC_ID = "bc_promo"


@pytest.fixture(autouse=True)
def _reset_state(tmp_path):
    users_file = tmp_path / "authorized.json"
    auth_users.configure(
        users_file=str(users_file),
        max_users=20,
        seed_user_ids=[VIP_ID],
        admin_id=ADMIN_ID,
    )
    auth_users.set_admin_id(ADMIN_ID)
    state.history.clear()
    state.reply_gen.clear()
    state.timers.clear()
    state.timer_schedule.clear()
    state.chat_bc.clear()
    state.pending_msg.clear()
    state.chat_meta.clear()
    state.connections.clear()
    yield
    state.history.clear()
    state.reply_gen.clear()
    state.timers.clear()
    state.timer_schedule.clear()
    state.chat_bc.clear()
    state.pending_msg.clear()
    state.chat_meta.clear()
    state.connections.clear()


def _msg(
    *,
    chat_id: int,
    sender_id: int,
    text: str,
    message_id: int = 10,
    username: str = "buyer",
    bc_id: str = BC_ID,
) -> MagicMock:
    msg = MagicMock()
    msg.business_connection_id = bc_id
    msg.chat.id = chat_id
    msg.chat.type = "private"
    msg.text = text
    msg.caption = None
    for name in (
        "photo", "video", "video_note", "voice", "audio",
        "document", "sticker", "animation", "paid_media",
    ):
        setattr(msg, name, None)
    msg.from_user.id = sender_id
    msg.from_user.username = username
    msg.from_user.first_name = username
    msg.message_id = message_id
    return msg


@pytest.mark.asyncio
async def test_non_vip_exact_trigger_schedules_and_sets_pending(monkeypatch):
    """Exact trigger on non-VIP: schedule promo + pending_msg/chat_bc/chat_meta."""
    monkeypatch.setattr(business, "OBSERVE_UNAUTHORIZED", True)
    state.connections[BC_ID] = ADMIN_ID

    mock_schedule = AsyncMock(return_value=True)
    context = AsyncMock()

    with (
        patch("handlers.business.promo_info.schedule_promo_reply", mock_schedule),
        patch("handlers.business.auto_reply", new_callable=AsyncMock) as mock_ar,
        patch("services.reengagement.touch_inbound") as mock_touch,
    ):
        await business._handle_business_message(
            _msg(
                chat_id=NON_VIP_CHAT,
                sender_id=NON_VIP_SENDER,
                text=NON_VIP_PROMO_TRIGGER,
                message_id=42,
                username="buyer",
            ),
            context,
            edited=False,
        )

    mock_schedule.assert_awaited_once()
    kwargs = mock_schedule.await_args.kwargs
    assert kwargs["chat_id"] == NON_VIP_CHAT
    assert kwargs["bc_id"] == BC_ID
    assert kwargs["username"] == "buyer"
    assert state.pending_msg[NON_VIP_CHAT] == 42
    assert state.chat_bc[NON_VIP_CHAT] == BC_ID
    assert state.chat_meta[NON_VIP_CHAT]["username"] == "buyer"
    assert NON_VIP_CHAT not in state.timer_schedule
    mock_ar.assert_not_awaited()
    mock_touch.assert_not_called()


@pytest.mark.asyncio
async def test_non_vip_non_trigger_does_not_schedule(monkeypatch):
    monkeypatch.setattr(business, "OBSERVE_UNAUTHORIZED", True)
    state.connections[BC_ID] = ADMIN_ID

    mock_schedule = AsyncMock(return_value=True)
    with patch("handlers.business.promo_info.schedule_promo_reply", mock_schedule):
        await business._handle_business_message(
            _msg(
                chat_id=NON_VIP_CHAT,
                sender_id=NON_VIP_SENDER,
                text="hola, quiero info",
            ),
            AsyncMock(),
            edited=False,
        )

    mock_schedule.assert_not_awaited()
    assert NON_VIP_CHAT not in state.pending_msg


@pytest.mark.asyncio
async def test_flag_off_does_not_schedule(monkeypatch):
    monkeypatch.setattr(business, "OBSERVE_UNAUTHORIZED", True)
    monkeypatch.setattr(
        "handlers.business.NON_VIP_PROMO_AUTOREPLY_ENABLED", False,
    )
    state.connections[BC_ID] = ADMIN_ID

    mock_schedule = AsyncMock(return_value=True)
    with patch("handlers.business.promo_info.schedule_promo_reply", mock_schedule):
        await business._handle_business_message(
            _msg(
                chat_id=NON_VIP_CHAT,
                sender_id=NON_VIP_SENDER,
                text=NON_VIP_PROMO_TRIGGER,
            ),
            AsyncMock(),
            edited=False,
        )

    mock_schedule.assert_not_awaited()
    assert NON_VIP_CHAT not in state.pending_msg


@pytest.mark.asyncio
async def test_flag_on_schedules_even_when_observe_off(monkeypatch):
    """Flag independent of OBSERVE_UNAUTHORIZED."""
    monkeypatch.setattr(business, "OBSERVE_UNAUTHORIZED", False)
    monkeypatch.setattr(
        "handlers.business.NON_VIP_PROMO_AUTOREPLY_ENABLED", True,
    )
    state.connections[BC_ID] = ADMIN_ID

    mock_schedule = AsyncMock(return_value=True)
    with patch("handlers.business.promo_info.schedule_promo_reply", mock_schedule):
        await business._handle_business_message(
            _msg(
                chat_id=NON_VIP_CHAT,
                sender_id=NON_VIP_SENDER,
                text=NON_VIP_PROMO_TRIGGER,
                message_id=99,
            ),
            AsyncMock(),
            edited=False,
        )

    mock_schedule.assert_awaited_once()
    assert state.pending_msg[NON_VIP_CHAT] == 99
    assert state.chat_bc[NON_VIP_CHAT] == BC_ID


@pytest.mark.asyncio
async def test_edited_message_does_not_schedule(monkeypatch):
    monkeypatch.setattr(business, "OBSERVE_UNAUTHORIZED", True)
    state.connections[BC_ID] = ADMIN_ID

    mock_schedule = AsyncMock(return_value=True)
    with patch("handlers.business.promo_info.schedule_promo_reply", mock_schedule):
        await business._handle_business_message(
            _msg(
                chat_id=NON_VIP_CHAT,
                sender_id=NON_VIP_SENDER,
                text=NON_VIP_PROMO_TRIGGER,
            ),
            AsyncMock(),
            edited=True,
        )

    mock_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_vip_trigger_uses_llm_path_not_promo(monkeypatch):
    """Authorized VIP with trigger text still goes through auto_reply, not promo."""
    state.connections[BC_ID] = ADMIN_ID

    mock_schedule = AsyncMock(return_value=True)
    created_tasks = []

    def capture_task(coro):
        # Do not run auto_reply; just prove VIP path scheduled a task.
        created_tasks.append(coro)
        coro.close()
        task = MagicMock(name="vip_auto_reply_task")
        return task

    with (
        patch("handlers.business.promo_info.schedule_promo_reply", mock_schedule),
        patch("handlers.business.compute_reply_delay", return_value=60.0),
        patch("handlers.business.auto_reply", new_callable=AsyncMock),
        patch("handlers.business.asyncio.create_task", side_effect=capture_task),
        patch("handlers.business.needs_escalation", return_value=None),
        patch("handlers.business._save_runtime_state"),
        patch("services.reengagement.touch_inbound"),
        patch("handlers.business.append_message"),
        patch("handlers.business.ensure_loaded"),
    ):
        await business._handle_business_message(
            _msg(
                chat_id=VIP_CHAT,
                sender_id=VIP_ID,
                text=NON_VIP_PROMO_TRIGGER,
                username="vipuser",
            ),
            AsyncMock(),
            edited=False,
        )

    mock_schedule.assert_not_awaited()
    assert VIP_CHAT in state.timer_schedule  # VIP path writes schedule
    assert VIP_CHAT in state.timers
    assert len(created_tasks) == 1


@pytest.mark.asyncio
async def test_mid_wait_inbound_does_not_reschedule(monkeypatch):
    """Second inbound while timer active: schedule returns False / not re-stacked."""
    monkeypatch.setattr(business, "OBSERVE_UNAUTHORIZED", True)
    state.connections[BC_ID] = ADMIN_ID
    # Simulate active promo wait
    state.timers[NON_VIP_CHAT] = MagicMock(name="active_promo")

    mock_schedule = AsyncMock(return_value=False)
    with patch("handlers.business.promo_info.schedule_promo_reply", mock_schedule):
        await business._handle_business_message(
            _msg(
                chat_id=NON_VIP_CHAT,
                sender_id=NON_VIP_SENDER,
                text=NON_VIP_PROMO_TRIGGER,
                message_id=77,
            ),
            AsyncMock(),
            edited=False,
        )

    # Handler still invokes schedule (service decides ignore); pending updated for read
    mock_schedule.assert_awaited_once()
    assert state.pending_msg[NON_VIP_CHAT] == 77
    assert NON_VIP_CHAT not in state.timer_schedule
    # Original timer object still present (handler must not cancel/replace)
    assert state.timers[NON_VIP_CHAT] is not None


@pytest.mark.asyncio
async def test_schedule_never_writes_timer_schedule_via_service(promo_info_db, monkeypatch):
    """Regression: schedule_promo_reply itself leaves timer_schedule empty."""
    from services import promo_info

    state.timers.clear()
    state.timer_schedule.clear()
    monkeypatch.setattr(promo_info, "compute_promo_delay_sec", lambda: 0.01)

    created_coros = []

    def capture_create(coro):
        created_coros.append(coro)
        coro.close()
        return MagicMock(name="task")

    monkeypatch.setattr("services.promo_info.asyncio.create_task", capture_create)

    ok = await promo_info.schedule_promo_reply(
        AsyncMock(),
        chat_id=NON_VIP_CHAT,
        username="buyer",
        bc_id=BC_ID,
        vip_id=NON_VIP_SENDER,
    )
    assert ok is True
    assert state.timer_schedule == {}
    assert NON_VIP_CHAT in state.timers
    state.timers.clear()
