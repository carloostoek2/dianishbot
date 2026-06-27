"""Unit tests for MemoryService notes CRUD and get_context_block."""

import json
import pytest
from datetime import datetime
from unittest.mock import patch

from services.memory import MemoryService, NOTES_KEY


@pytest.fixture
def memory_svc(test_db):
    return MemoryService(test_db)


def test_add_note_appends_with_timestamp(memory_svc):
    uid = 1001
    memory_svc.add_note(uid, "Primera nota")
    memory_svc.add_note(uid, "Segunda nota")
    notes = memory_svc.get_notes(uid)
    assert len(notes) == 2
    assert notes[0]["text"] == "Primera nota"
    assert notes[1]["text"] == "Segunda nota"
    for n in notes:
        datetime.fromisoformat(n["date"])


def test_get_notes_empty(memory_svc):
    assert memory_svc.get_notes(9999) == []


def test_get_notes_corrupt_json(memory_svc, test_db, caplog):
    uid = 1002
    test_db.execute(
        "INSERT INTO user_memory (user_id, key, value, source, confidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, NOTES_KEY, "not-valid-json{{{", "diana_manual", 100, "2026-01-01"),
    )
    test_db.commit()
    with caplog.at_level("WARNING"):
        notes = memory_svc.get_notes(uid)
    assert notes == []
    assert any(str(uid) in r.message for r in caplog.records)


def test_clear_notes_idempotent(memory_svc):
    uid = 1003
    memory_svc.add_note(uid, "algo")
    assert memory_svc.clear_notes(uid) is True
    assert memory_svc.clear_notes(uid) is False


def test_add_note_never_calls_set_fact(memory_svc):
    """Critical: notes JSON must bypass set_fact 300-char truncation."""
    uid = 1007
    with patch.object(memory_svc, "set_fact") as mock_set_fact:
        memory_svc.add_note(uid, "Nota que no debe pasar por set_fact")
    mock_set_fact.assert_not_called()
    assert memory_svc.get_notes(uid)[0]["text"] == "Nota que no debe pasar por set_fact"


def test_multi_note_no_truncation(memory_svc, test_db):
    uid = 1004
    long_text = (
        "Nota larga para superar trescientos caracteres en el JSON acumulado "
        * 3
    )
    for i in range(6):
        memory_svc.add_note(uid, f"{long_text} #{i}")
    notes = memory_svc.get_notes(uid)
    assert len(notes) == 6
    raw = test_db.execute(
        "SELECT value FROM user_memory WHERE user_id=? AND key=?",
        (uid, NOTES_KEY),
    ).fetchone()[0]
    assert len(raw) > 300
    assert len(json.loads(raw)) == 6


def test_get_context_block_notes_before_facts(memory_svc):
    uid = 1005
    memory_svc.set_fact(uid, "name", "Carlos")
    memory_svc.add_note(uid, "No hacer bromas pesadas")
    block = memory_svc.get_context_block(uid)
    assert "NOTAS PERSONALES" in block
    assert "máxima prioridad" in block
    assert "Datos generales" in block
    assert block.index("NOTAS PERSONALES") < block.index("Datos generales")
    facts_section = block.split("Datos generales")[-1]
    assert "notes" not in facts_section


def test_get_context_block_last_five_only(memory_svc):
    uid = 1006
    for i in range(7):
        memory_svc.add_note(uid, f"Nota numero {i}")
    block = memory_svc.get_context_block(uid)
    assert "Nota numero 0" not in block
    assert "Nota numero 1" not in block
    assert "Nota numero 2" in block
    assert "Nota numero 6" in block


def test_get_context_block_empty(memory_svc):
    assert memory_svc.get_context_block(9999) == ""


def test_get_context_block_corrupt_only_notes_row(memory_svc, test_db):
    uid = 1008
    test_db.execute(
        "INSERT INTO user_memory (user_id, key, value, source, confidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, NOTES_KEY, "not-valid-json{{{", "diana_manual", 100, "2026-01-01"),
    )
    test_db.commit()
    assert memory_svc.get_context_block(uid) == ""


def test_add_note_after_corrupt_json(memory_svc, test_db, caplog):
    uid = 1009
    test_db.execute(
        "INSERT INTO user_memory (user_id, key, value, source, confidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, NOTES_KEY, "not-valid-json{{{", "diana_manual", 100, "2026-01-01"),
    )
    test_db.commit()
    with caplog.at_level("ERROR"):
        assert memory_svc.add_note(uid, "Nueva nota") is True
    notes = memory_svc.get_notes(uid)
    assert len(notes) == 1
    assert notes[0]["text"] == "Nueva nota"


def test_add_note_non_list_json(memory_svc, test_db):
    uid = 1010
    test_db.execute(
        "INSERT INTO user_memory (user_id, key, value, source, confidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, NOTES_KEY, "{}", "diana_manual", 100, "2026-01-01"),
    )
    test_db.commit()
    assert memory_svc.add_note(uid, "Recuperada") is True
    assert memory_svc.get_notes(uid)[0]["text"] == "Recuperada"


def test_get_notes_non_list_json(memory_svc, test_db, caplog):
    uid = 1011
    test_db.execute(
        "INSERT INTO user_memory (user_id, key, value, source, confidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, NOTES_KEY, "{}", "diana_manual", 100, "2026-01-01"),
    )
    test_db.commit()
    with caplog.at_level("WARNING"):
        assert memory_svc.get_notes(uid) == []


def test_get_context_block_malformed_note_missing_text(memory_svc, test_db):
    uid = 1012
    test_db.execute(
        "INSERT INTO user_memory (user_id, key, value, source, confidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, NOTES_KEY, '[{"date": "2026-01-01"}]', "diana_manual", 100, "2026-01-01"),
    )
    test_db.commit()
    assert memory_svc.get_context_block(uid) == ""


def test_add_note_returns_false_on_empty(memory_svc):
    assert memory_svc.add_note(1013, "   ") is False
    assert memory_svc.get_notes(1013) == []


def test_add_note_returns_true_on_success(memory_svc):
    assert memory_svc.add_note(1014, "válida") is True


def test_add_note_collapses_newlines(memory_svc):
    uid = 1015
    memory_svc.add_note(uid, "línea1\nlínea2\rtercera")
    assert memory_svc.get_notes(uid)[0]["text"] == "línea1 línea2 tercera"


def test_add_note_caps_at_500_chars(memory_svc):
    uid = 1016
    long_text = "x" * 600
    memory_svc.add_note(uid, long_text)
    assert len(memory_svc.get_notes(uid)[0]["text"]) == 500


def test_get_context_block_notes_only_no_facts(memory_svc):
    uid = 1017
    memory_svc.add_note(uid, "Solo nota")
    block = memory_svc.get_context_block(uid)
    assert "NOTAS PERSONALES" in block
    assert "Datos generales" not in block


def test_get_context_block_non_string_note_text_coerced(memory_svc, test_db, caplog):
    uid = 1018
    test_db.execute(
        "INSERT INTO user_memory (user_id, key, value, source, confidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, NOTES_KEY, '[{"text": 12345, "date": "2026-01-01"}]', "diana_manual", 100, "2026-01-01"),
    )
    test_db.commit()
    with caplog.at_level("WARNING"):
        block = memory_svc.get_context_block(uid)
    assert "12345" in block
    assert "NOTAS PERSONALES" in block


def test_add_note_strips_non_printable(memory_svc):
    uid = 1019
    assert memory_svc.add_note(uid, "hola\x00\x01mundo") is True
    assert memory_svc.get_notes(uid)[0]["text"] == "holamundo"


def test_get_context_block_non_string_date_coerced(memory_svc, test_db, caplog):
    uid = 1020
    test_db.execute(
        "INSERT INTO user_memory (user_id, key, value, source, confidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, NOTES_KEY, '[{"text": "ok", "date": 20260101}]', "diana_manual", 100, "2026-01-01"),
    )
    test_db.commit()
    with caplog.at_level("WARNING"):
        block = memory_svc.get_context_block(uid)
    assert "[20260101]" in block
    assert "ok" in block