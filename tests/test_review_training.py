"""Tests for scripts/review_training.py queue logic."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import review_training as rt  # noqa: E402


def _seed(db_path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            username TEXT,
            ts TEXT,
            context TEXT,
            bot_response TEXT,
            confidence INTEGER,
            topic TEXT,
            rating TEXT,
            correction TEXT,
            status TEXT DEFAULT 'pending'
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO examples
        (id, chat_id, username, ts, context, bot_response, confidence, topic, rating, correction, status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def test_approve_keeps_and_advances(tmp_path: Path):
    db = tmp_path / "t.db"
    progress = tmp_path / "p.json"
    ctx = json.dumps([{"role": "user", "content": "hola"}], ensure_ascii=False)
    _seed(
        db,
        [
            (1, 10, "u1", "2026-01-01", ctx, "resp1", 80, "saludo", None, None, "pending"),
            (2, 10, "u1", "2026-01-02", ctx, "resp2", 80, "saludo", "diana_manual", None, "reviewed"),
        ],
    )
    app = rt.ReviewApp(db, progress)

    first = app.next_payload()
    assert first["item"]["id"] == 1
    assert first["stats"]["remaining"] == 2

    out = app.decide(1, "approve")
    assert out["item"]["id"] == 2
    assert out["stats"]["approved"] == 1
    assert out["stats"]["remaining"] == 1

    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT status, rating FROM examples WHERE id=1"
        ).fetchone()
        assert row == ("reviewed", "good")
        assert conn.execute("SELECT COUNT(*) FROM examples").fetchone()[0] == 2


def test_discard_deletes_and_advances(tmp_path: Path):
    db = tmp_path / "t.db"
    progress = tmp_path / "p.json"
    ctx = json.dumps([{"role": "user", "content": "hola"}], ensure_ascii=False)
    _seed(
        db,
        [
            (5, 10, "u1", "2026-01-01", ctx, "resp1", 80, "saludo", "diana_manual", None, "reviewed"),
            (9, 10, "u1", "2026-01-02", ctx, "resp2", 80, "saludo", "good", None, "reviewed"),
        ],
    )
    app = rt.ReviewApp(db, progress)
    out = app.decide(5, "discard")
    assert out["item"]["id"] == 9
    assert out["stats"]["discarded"] == 1
    assert out["stats"]["remaining"] == 1

    with sqlite3.connect(str(db)) as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM examples ORDER BY id")]
        assert ids == [9]


def test_stale_id_rejected(tmp_path: Path):
    db = tmp_path / "t.db"
    progress = tmp_path / "p.json"
    ctx = json.dumps([{"role": "user", "content": "hola"}], ensure_ascii=False)
    _seed(
        db,
        [
            (1, 10, "u1", "2026-01-01", ctx, "resp1", 80, "saludo", "good", None, "reviewed"),
            (2, 10, "u1", "2026-01-02", ctx, "resp2", 80, "saludo", "good", None, "reviewed"),
        ],
    )
    app = rt.ReviewApp(db, progress)
    with pytest.raises(ValueError, match="stale"):
        app.decide(2, "approve")
