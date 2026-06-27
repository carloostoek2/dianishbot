from datetime import datetime
from zoneinfo import ZoneInfo

from config import DIANA_TIMEZONE, DIANA_WEEKLY_SCHEDULE

_WEEKDAYS_ES = (
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
)
_MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _in_time_range(hour: int, minute: int, start_h: int, end_h: int) -> bool:
    """True si hour:minute está en [start_h:00, end_h:00). end_h es exclusivo."""
    current = hour * 60 + minute
    return start_h * 60 <= current < end_h * 60


def resolve_current_activity(now: datetime) -> str:
    """Devuelve la actividad probable según día y hora en zona México."""
    hour, minute = now.hour, now.minute
    weekday = now.weekday()  # 0=lunes … 6=domingo

    if hour < 7:
        return "durmiendo o descansando"

    if weekday == 6:
        return "con mi hermana"

    if weekday == 5:
        if _in_time_range(hour, minute, 8, 12):
            return "clases de inglés"
        if hour >= 15:
            return "asesoría/ayuda con tareas a niños (voy casa por casa)"
        return "tiempo libre (puede estar en el cel)"

    if weekday <= 4 and _in_time_range(hour, minute, 9, 14):
        return "servicio social (instituto de adicciones)"

    if weekday <= 3 and _in_time_range(hour, minute, 16, 21):
        return "prácticas profesionales (casa hogar)"

    if weekday == 4 and _in_time_range(hour, minute, 17, 20):
        return "diplomado de gamificación"

    return "tiempo libre (puede estar en el cel)"


def format_mexico_datetime(now: datetime) -> str:
    """Formatea fecha/hora en español para Ciudad de México."""
    day_name = _WEEKDAYS_ES[now.weekday()]
    month_name = _MONTHS_ES[now.month - 1]
    return (
        f"{day_name} {now.day} de {month_name} de {now.year}, "
        f"{now.hour:02d}:{now.minute:02d} (Ciudad de México)"
    )


def build_temporal_context_block(now: datetime | None = None) -> str:
    """Bloque para inyectar al system prompt: hora actual + rutina semanal fija."""
    if now is None:
        now = datetime.now(ZoneInfo(DIANA_TIMEZONE))
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo(DIANA_TIMEZONE))
    else:
        now = now.astimezone(ZoneInfo(DIANA_TIMEZONE))

    activity = resolve_current_activity(now)
    time_str = format_mexico_datetime(now)

    return f"""
---
CONTEXTO TEMPORAL (México — consultar antes de responder sobre horarios o qué estoy haciendo)

Hora actual: {time_str}
Actividad probable ahora: {activity}

RUTINA SEMANAL FIJA:
{DIANA_WEEKLY_SCHEDULE}

Regla: nunca digas que estoy en servicio, prácticas, inglés o diplomado fuera de esos horarios.
De madrugada (00:00-07:00) estoy durmiendo o descansando, no en actividades del día.
---
"""