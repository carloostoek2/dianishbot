"""Per-chat asyncio.Lock for history and pending_approval writes."""

import asyncio

import pytest

import state
from state import chat_write_lock, pending_approval


@pytest.fixture(autouse=True)
def _reset_state():
    state.history.clear()
    state.pending_approval.clear()
    state._chat_locks.clear()
    yield
    state.history.clear()
    state.pending_approval.clear()
    state._chat_locks.clear()


async def _append_under_lock(chat_id: int, content: str) -> None:
    async with chat_write_lock(chat_id):
        msgs = state.history.setdefault(chat_id, [])
        msgs.append({"role": "user", "content": content})


@pytest.mark.asyncio
async def test_concurrent_append_same_chat_preserves_all_messages():
    chat_id = 1001
    n = 20
    await asyncio.gather(*[_append_under_lock(chat_id, f"m{i}") for i in range(n)])
    assert len(state.history[chat_id]) == n
    contents = {m["content"] for m in state.history[chat_id]}
    assert contents == {f"m{i}" for i in range(n)}


@pytest.mark.asyncio
async def test_concurrent_pending_approval_variant_append_not_corrupted():
    chat_id = 2002
    ex_id = 42
    pending_approval[ex_id] = {
        "chat_id": chat_id,
        "variants": [{"response": "v0", "confidence": 80, "topic": "t"}],
        "selected": 0,
        "regenerating": False,
    }

    async def add_variant(i: int) -> None:
        async with chat_write_lock(chat_id):
            pending_approval[ex_id]["variants"].append({
                "response": f"v{i}",
                "confidence": 70 + i,
                "topic": "t",
            })

    await asyncio.gather(*[add_variant(i) for i in range(1, 11)])
    variants = pending_approval[ex_id]["variants"]
    assert len(variants) == 11
    assert variants[0]["response"] == "v0"
    assert {v["response"] for v in variants[1:]} == {f"v{i}" for i in range(1, 11)}


@pytest.mark.asyncio
async def test_lock_for_chat_a_does_not_block_chat_b():
    a_holding = asyncio.Event()
    b_done = asyncio.Event()

    async def hold_chat_a():
        async with chat_write_lock(1):
            a_holding.set()
            await asyncio.sleep(0.05)

    async def write_chat_b():
        await a_holding.wait()
        async with chat_write_lock(2):
            state.history[2] = [{"role": "user", "content": "b"}]
            b_done.set()

    await asyncio.gather(hold_chat_a(), write_chat_b())
    assert b_done.is_set()
    assert state.history[2][0]["content"] == "b"