"""Tests for error_handler user-notification fallback logging."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.error_handler import error_handler


@pytest.mark.asyncio
async def test_notify_failure_logged_when_reply_raises(caplog):
    update = MagicMock()
    update.update_id = 1
    update.effective_user = MagicMock(id=99)
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock(side_effect=RuntimeError("send failed"))
    update.effective_chat = None
    update.callback_query = None

    context = MagicMock()
    context.error = ValueError("original")

    with caplog.at_level("WARNING", logger="diana"):
        await error_handler(update, context)

    assert any(
        "error_handler: no se pudo notificar al usuario" in r.message
        for r in caplog.records
    )