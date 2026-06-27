import asyncio
import sqlite3
import json
import logging
from datetime import datetime

# services/memory.py

log = logging.getLogger("diana")

# SECURITY NOTE (minimal hardening for PII high + validation medium, per review):
# Facts contain user PII (name etc). Sanitization applied on set.
# Treat as untrusted. No encryption per original design/PLAN.
# Shared conn with training (check_same_thread=False) documented; low concurrency use.

FACTS_TABLE = """
CREATE TABLE IF NOT EXISTS user_memory (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    key      TEXT NOT NULL,        -- "name", "occupation", "interests", etc.
    value    TEXT NOT NULL,
    source   TEXT DEFAULT 'auto',  -- "auto" | "diana_manual"
    confidence INTEGER DEFAULT 80, -- 0-100
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, key) ON CONFLICT REPLACE
)"""

def schedule_memory_extract(
    service: "MemoryService | None",
    user_id: int,
    conversation: list[dict],
    llm_call_fn,
) -> None:
    """Background fact extraction after a successful delivery."""
    if service is None:
        return
    task = asyncio.create_task(
        service.extract_and_update(user_id, conversation, llm_call_fn),
    )

    def _log_extract_exc(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            log.error(f"memory extract_and_update error: {exc}")

    task.add_done_callback(_log_extract_exc)


KEYS_TRACKED = [
    "name",               # cómo se llama
    "occupation",         # trabajo / estudio
    "location",           # de dónde es
    "interests",          # hobbies, gustos
    "relationship",       # estado sentimental
    "personality",        # directo, tímido, gracioso
    "last_topic",         # último tema conversado
    "notable",            # dato curioso / importante
]

NOTES_KEY = "notes"
MAX_NOTE_TEXT_CHARS = 500


def extract_note_display_text(
    entry: object, user_id: int | None = None,
) -> str | None:
    """Return stripped display text for a note entry, or None if unusable."""
    if not isinstance(entry, dict):
        if user_id is not None:
            log.warning(
                f"Skipping non-dict note entry for user {user_id} "
                f"({type(entry).__name__})"
            )
        return None
    raw = entry.get("text", "")
    if not isinstance(raw, str):
        if raw is None:
            return None
        log.warning(
            f"Note text is not str for user {user_id} "
            f"({type(raw).__name__}), coercing"
        )
        raw = str(raw)
    text = raw.strip()
    return text if text else None


def extract_note_display_date(
    entry: object, user_id: int | None = None,
) -> str:
    """Return date prefix (max 10 chars) for display, or \"\" if unusable."""
    if not isinstance(entry, dict):
        return ""
    raw = entry.get("date", "")
    if raw is None:
        return ""
    if not isinstance(raw, str):
        log.warning(
            f"Note date is not str for user {user_id} "
            f"({type(raw).__name__}), coercing"
        )
        raw = str(raw)
    return raw.strip()[:10]


# PII handling note (for security review):
# Facts are auto-extracted and stored plaintext (same class as training data).
# Basic sanitization (printable + <=200 chars) applied in set_fact before persist.
# No encryption/retention per original design; caller (diana) controls.
# get_facts/get_context_block return as-is for prompt use.

class MemoryService:
    """
    WARNING (security): Stores user facts (PII: name, occupation, location, relationship,
    interests, personality, etc.) in plaintext sqlite. Auto-extracted from convos.
    No consent, retention, or encryption per design. For admin/internal use only.
    Sanitization applied on set but treat all facts as untrusted user data.
    """
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        # Shared synchronous sqlite conn (check_same_thread=False) with training.
        # Design choice from original PLAN/refactor (shared DB, no new deps).
        # Mitigates reentrancy for this use case but recommend aiosqlite/pool
        # + WAL for future to avoid locks under concurrent main+bg tasks (medium).
        self._init_tables()

    def _init_tables(self):
        self.db.execute(FACTS_TABLE)
        self.db.commit()

    def set_fact(self, user_id: int, key: str, value: str,
                 source="auto", confidence=80):
        if not value:
            return
        # Basic sanitization (per security review high PII Finding1 + medium validation Finding7):
        # cap to 300 chars, strip, drop non-printable + newlines (minimal to limit PII bloat and injection).
        # Still user-derived plaintext per original design; no encryption/retention added.
        s = str(value)[:300].strip()
        s = ''.join(c for c in s if c.isprintable() or c == ' ')
        s = s.replace('\n',' ').replace('\r',' ')[:300]
        if not s:
            return
        self.db.execute(
            "INSERT OR REPLACE INTO user_memory "
            "(user_id, key, value, source, confidence, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, key, s, source, confidence,
             datetime.now().isoformat())
        )
        self.db.commit()

    def get_facts(self, user_id: int) -> dict[str, str]:
        rows = self.db.execute(
            "SELECT key, value FROM user_memory WHERE user_id=? "
            "ORDER BY updated_at DESC", (user_id,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def _sanitize_note_text(self, text: str) -> str:
        """Per-note sanitization — does NOT cap the JSON blob."""
        s = str(text).strip()[:MAX_NOTE_TEXT_CHARS]
        s = s.replace("\n", " ").replace("\r", " ")
        s = "".join(c for c in s if c.isprintable() or c == " ")
        return s.strip()

    def _persist_notes(self, user_id: int, notes: list[dict]) -> None:
        """Direct SQL for notes JSON — bypasses set_fact 300-char truncation."""
        payload = json.dumps(notes, ensure_ascii=False)
        self.db.execute(
            "INSERT OR REPLACE INTO user_memory "
            "(user_id, key, value, source, confidence, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, NOTES_KEY, payload, "diana_manual", 100,
             datetime.now().isoformat()),
        )
        self.db.commit()

    def _load_notes_list(
        self, raw: str, user_id: int, *, on_write: bool = False,
    ) -> list[dict]:
        """Parse notes JSON; corrupt or wrong-type payloads become []."""
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as e:
            if on_write:
                log.error(
                    f"Corrupt notes JSON for user {user_id} on write, "
                    f"resetting to []: {e}"
                )
            else:
                log.warning(
                    f"Corrupt notes JSON for user {user_id}, returning []: {e}"
                )
            return []
        if not isinstance(parsed, list):
            log.warning(
                f"Notes JSON for user {user_id} is not a list "
                f"({type(parsed).__name__}), using []"
            )
            return []
        return parsed

    def add_note(self, user_id: int, note_text: str) -> bool:
        """Añade nota manual de Diana. Retorna True si se persistió."""
        sanitized = self._sanitize_note_text(note_text)
        if not sanitized:
            return False
        row = self.db.execute(
            "SELECT value FROM user_memory WHERE user_id=? AND key=?",
            (user_id, NOTES_KEY),
        ).fetchone()
        notes: list[dict] = []
        if row:
            notes = self._load_notes_list(row[0], user_id, on_write=True)
        notes.append({
            "text": sanitized,
            "date": datetime.now().isoformat(),
        })
        self._persist_notes(user_id, notes)
        return True

    def get_notes(self, user_id: int) -> list[dict]:
        """Notas manuales de Diana para un usuario."""
        row = self.db.execute(
            "SELECT value FROM user_memory WHERE user_id=? AND key=?",
            (user_id, NOTES_KEY),
        ).fetchone()
        if not row:
            return []
        return self._load_notes_list(row[0], user_id, on_write=False)

    def clear_notes(self, user_id: int) -> bool:
        """Borra todas las notas. Retorna True si había algo."""
        row = self.db.execute(
            "SELECT id FROM user_memory WHERE user_id=? AND key=?",
            (user_id, NOTES_KEY),
        ).fetchone()
        if not row:
            return False
        self.db.execute(
            "DELETE FROM user_memory WHERE user_id=? AND key=?",
            (user_id, NOTES_KEY),
        )
        self.db.commit()
        return True

    def _displayable_notes(self, user_id: int) -> list[dict]:
        """Notes with non-empty text — skips malformed entries."""
        displayable = []
        for n in self.get_notes(user_id):
            text = extract_note_display_text(n, user_id)
            if not text:
                continue
            date = extract_note_display_date(n, user_id)
            displayable.append({"text": text, "date": date})
        return displayable

    def get_context_block(self, user_id: int) -> str:
        """Devuelve bloque para inyectar al system prompt.
        (Per design: hardening for untrusted data applied only at injection site in llm.py;
        this returns the plain block or "" to preserve 0 behavior change.)
        """
        facts = self.get_facts(user_id)
        display_notes = self._displayable_notes(user_id)
        auto_facts = {k: v for k, v in facts.items() if k != NOTES_KEY}

        if not display_notes and not auto_facts:
            return ""

        lines = ["\n\n---\nSOBRE ESTE USUARIO (recuerdas esto de sesiones anteriores):"]

        if display_notes:
            lines.append(
                "\nNOTAS PERSONALES (máxima prioridad, sígue estas instrucciones siempre):"
            )
            for n in display_notes[-5:]:
                lines.append(f"  [{n['date']}] {n['text']}")

        if auto_facts:
            lines.append("\nDatos generales:")
            labels = {
                "name": "Se llama",
                "occupation": "Trabaja/estudia en",
                "location": "Es de",
                "interests": "Le interesa",
                "relationship": "Estado sentimental",
                "personality": "Su estilo",
                "last_topic": "Último tema",
                "notable": "Dato importante",
            }
            for key, value in auto_facts.items():
                label = labels.get(key, key)
                lines.append(f"  - {label}: {value}")

        lines.append("---")
        return "\n".join(lines)

    async def extract_and_update(
        self,
        user_id: int,
        conversation: list[dict],
        llm_call_fn,  # referencia a get_diana_response o función similar
    ):
        """
        Llama al LLM en background para extraer hechos nuevos.
        Se ejecuta como asyncio.create_task() — no bloquea la entrega.
        Solo corre si hay al menos 2 turnos de usuario.
        """
        user_turns = [m for m in conversation if m["role"] == "user"]
        if len(user_turns) < 2:
            return

        existing = self.get_facts(user_id)
        existing_str = json.dumps(existing, ensure_ascii=False)
        convo_str = "\n".join(
            f"{'Usuario' if m['role']=='user' else 'Diana'}: {m['content']}"
            for m in conversation[-10:]
        )

        prompt = f"""Extrae hechos relevantes sobre el usuario de esta conversación.
Hechos ya conocidos: {existing_str}

Conversación:
{convo_str}

Responde SOLO con JSON. Solo incluye claves con información NUEVA o CORREGIDA.
Claves válidas: name, occupation, location, interests, relationship, personality, last_topic, notable.
Si no hay nada nuevo, responde {{}}.
Ejemplo: {{"name": "Carlos", "interests": "gaming y música metal"}}"""

        raw, _err = await llm_call_fn(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        if not raw:
            return
        response = raw
        try:
            facts = json.loads(response)
            for key, value in facts.items():
                if key in KEYS_TRACKED and value:
                    self.set_fact(user_id, key, str(value),
                                  source="auto", confidence=75)
        except (json.JSONDecodeError, TypeError) as e:
            log.warning(f"memory extract JSON parse failed for user {user_id}: {e}")
