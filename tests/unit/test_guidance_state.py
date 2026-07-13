"""Runtime state: pending_guidance persisted; awaiting_guidance_answer is not."""

import json
from pathlib import Path

import pytest

import state
from state import (
    _build_runtime_snapshot,
    _load_runtime_state,
    _save_runtime_state,
    awaiting_guidance_answer,
    pending_guidance,
    timer_schedule,
)


@pytest.fixture
def runtime_file(tmp_path, monkeypatch):
    path = tmp_path / "diana_runtime.json"
    monkeypatch.setattr(state, "RUNTIME_STATE_FILE", str(path))
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture(autouse=True)
def _reset_state():
    pending_guidance.clear()
    awaiting_guidance_answer.clear()
    timer_schedule.clear()
    state.pending_approval.clear()
    state.pending_escalations.clear()
    state.reply_gen.clear()
    state.history.clear()
    state.chat_bc.clear()
    state.pending_msg.clear()
    state.chat_meta.clear()
    yield
    pending_guidance.clear()
    awaiting_guidance_answer.clear()
    timer_schedule.clear()
    state.pending_approval.clear()
    state.pending_escalations.clear()
    state.reply_gen.clear()
    state.history.clear()
    state.chat_bc.clear()
    state.pending_msg.clear()
    state.chat_meta.clear()


def test_pending_guidance_included_in_snapshot():
    pending_guidance[7] = {
        "chat_id": 100,
        "bc_id": "bc_x",
        "username": "vip",
        "gen": 2,
        "topic": "limites",
        "gap_question": "¿Puedo ofrecer X?",
        "draft_response": "tentativo",
        "confidence": 70,
        "created_at": "2026-07-13T12:00:00",
    }
    snap = _build_runtime_snapshot()
    assert "7" in snap["pending_guidance"]
    assert snap["pending_guidance"]["7"]["chat_id"] == 100
    assert snap["pending_guidance"]["7"]["gap_question"] == "¿Puedo ofrecer X?"


def test_awaiting_guidance_answer_not_in_snapshot():
    awaiting_guidance_answer[555] = 7
    pending_guidance[7] = {
        "chat_id": 100,
        "bc_id": "bc_x",
        "username": "vip",
        "gen": 1,
        "topic": "t",
        "gap_question": "q",
        "draft_response": "d",
        "confidence": 50,
        "created_at": "2026-07-13T12:00:00",
    }
    snap = _build_runtime_snapshot()
    assert "awaiting_guidance_answer" not in snap
    assert 555 in awaiting_guidance_answer  # still runtime-only


def test_pending_guidance_roundtrip_save_load(runtime_file: Path):
    pending_guidance[11] = {
        "chat_id": 200,
        "bc_id": "bc_y",
        "username": "alice",
        "gen": 3,
        "topic": "precios",
        "gap_question": "¿Descuento?",
        "draft_response": "borrador",
        "confidence": 80,
        "created_at": "2026-07-13T13:00:00",
    }
    awaiting_guidance_answer[999] = 11
    _save_runtime_state()

    data = json.loads(runtime_file.read_text(encoding="utf-8"))
    assert "11" in data["pending_guidance"]
    assert "awaiting_guidance_answer" not in data

    pending_guidance.clear()
    awaiting_guidance_answer.clear()
    _load_runtime_state()

    assert 11 in pending_guidance
    assert pending_guidance[11]["username"] == "alice"
    assert pending_guidance[11]["gen"] == 3
    assert awaiting_guidance_answer == {}  # not restored


def test_pending_guidance_keeps_runtime_file(runtime_file: Path):
    pending_guidance[1] = {
        "chat_id": 50,
        "bc_id": "bc",
        "username": "u",
        "gen": 1,
        "topic": "t",
        "gap_question": "q",
        "draft_response": "d",
        "confidence": 60,
        "created_at": "2026-07-13T00:00:00",
    }
    _save_runtime_state()
    assert runtime_file.exists()


def test_active_chat_ids_includes_pending_guidance():
    pending_guidance[3] = {
        "chat_id": 777,
        "bc_id": "bc",
        "username": "vip",
        "gen": 1,
        "topic": "t",
        "gap_question": "q",
        "draft_response": "d",
        "confidence": 50,
        "created_at": "2026-07-13T00:00:00",
    }
    active = state._active_chat_ids()
    assert 777 in active
