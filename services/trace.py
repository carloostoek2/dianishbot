"""Traza global de llamadas al LLM — activable desde admin para debugging."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import TRACE_FILE

log = logging.getLogger("diana")

_enabled: bool = False


def enable() -> None:
    global _enabled
    _enabled = True
    log.info("Trace LLM activado")


def disable() -> None:
    global _enabled
    _enabled = False
    log.info("Trace LLM desactivado")


def is_enabled() -> bool:
    return _enabled


def toggle() -> bool:
    if _enabled:
        disable()
    else:
        enable()
    return _enabled


def format_estado_line() -> str:
    estado = "ON" if _enabled else "OFF"
    return f"*Trace LLM:* {estado}"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def trace_call(chat_id: int, *, injected: dict[str, Any], output: dict[str, Any]) -> None:
    if not _enabled:
        return

    entry = {
        "ts": _ts(),
        "chat_id": chat_id,
        **injected,
        "output": output,
    }

    path = Path(TRACE_FILE)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.error(f"Error escribiendo trace: {e}")
