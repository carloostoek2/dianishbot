"""Router update deduplication (LRU + TTL)."""

import pytest
from unittest.mock import AsyncMock, patch

from handlers.router import DEDUP_TTL_SEC, _dedup_cache, process_update


@pytest.fixture(autouse=True)
def _clear_dedup_cache():
    _dedup_cache.clear()
    yield
    _dedup_cache.clear()


@pytest.mark.asyncio
async def test_same_update_id_skips_second_call(make_update, make_context):
    update = make_update(update_id=42)
    ctx = make_context()

    with patch(
        "handlers.router._handle_business_message",
        new_callable=AsyncMock,
    ) as mock_handler:
        await process_update(update, ctx)
        await process_update(update, ctx)

    assert mock_handler.await_count == 1


@pytest.mark.asyncio
async def test_same_callback_query_id_different_update_id_skipped(
    make_callback_update, make_context,
):
    upd1 = make_callback_update(data="a:approve:1", update_id=100)
    upd2 = make_callback_update(data="a:approve:1", update_id=101)
    ctx = make_context()

    with patch(
        "handlers.router.handle_callback",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_cb:
        await process_update(upd1, ctx)
        await process_update(upd2, ctx)

    assert mock_cb.await_count == 1


@pytest.mark.asyncio
async def test_different_update_ids_both_invoke_handler(make_update, make_context):
    upd1 = make_update(update_id=1)
    upd2 = make_update(update_id=2)
    ctx = make_context()

    with patch(
        "handlers.router._handle_business_message",
        new_callable=AsyncMock,
    ) as mock_handler:
        await process_update(upd1, ctx)
        await process_update(upd2, ctx)

    assert mock_handler.await_count == 2


@pytest.mark.asyncio
async def test_ttl_expired_allows_reprocess(make_update, make_context):
    update = make_update(update_id=77)
    ctx = make_context()
    t0 = 1000.0

    with (
        patch("handlers.router.time.monotonic", side_effect=[t0, t0 + DEDUP_TTL_SEC]),
        patch(
            "handlers.router._handle_business_message",
            new_callable=AsyncMock,
        ) as mock_handler,
    ):
        await process_update(update, ctx)
        await process_update(update, ctx)

    assert mock_handler.await_count == 2


@pytest.mark.asyncio
async def test_duplicate_callback_answers_query(make_mock_callback_update, make_context):
    upd = make_mock_callback_update(data="a:approve:1")
    upd.update_id = 200
    upd.callback_query.id = "cb_dup_test"
    ctx = make_context()

    with patch(
        "handlers.router.handle_callback",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await process_update(upd, ctx)
        await process_update(upd, ctx)

    assert upd.callback_query.answer.await_count == 1