"""Unit tests for temporal context injection (services/schedule.py)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from config import DIANA_WEEKLY_SCHEDULE
from services.schedule import (
    build_temporal_context_block,
    format_mexico_datetime,
    resolve_current_activity,
)

TZ = ZoneInfo("America/Mexico_City")


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


class TestResolveCurrentActivity:
    @pytest.mark.parametrize(
        "now,expected",
        [
            (_dt(2026, 6, 24, 2, 30), "durmiendo o descansando"),  # miércoles madrugada
            (_dt(2026, 6, 24, 11, 0), "servicio social (instituto de adicciones)"),  # miércoles
            (_dt(2026, 6, 25, 18, 0), "prácticas profesionales (casa hogar)"),  # jueves
            (_dt(2026, 6, 26, 18, 0), "diplomado de gamificación"),  # viernes
            (_dt(2026, 6, 27, 10, 0), "clases de inglés"),  # sábado
            (_dt(2026, 6, 27, 16, 0), "asesoría/ayuda con tareas a niños (voy casa por casa)"),
            (_dt(2026, 6, 28, 12, 0), "con mi hermana"),  # domingo
            (_dt(2026, 6, 26, 15, 0), "tiempo libre (puede estar en el cel)"),  # vie tarde
        ],
    )
    def test_activity_by_time(self, now, expected):
        assert resolve_current_activity(now) == expected


class TestFormatMexicoDatetime:
    def test_spanish_format(self):
        now = _dt(2026, 6, 27, 14, 35)
        assert format_mexico_datetime(now) == (
            "sábado 27 de junio de 2026, 14:35 (Ciudad de México)"
        )


class TestBuildTemporalContextBlock:
    def test_contains_schedule_table_and_activity(self):
        now = _dt(2026, 6, 24, 2, 30)
        block = build_temporal_context_block(now)
        assert "CONTEXTO TEMPORAL" in block
        assert "miércoles 24 de junio de 2026, 02:30" in block
        assert "durmiendo o descansando" in block
        assert "Servicio social" in block
        assert DIANA_WEEKLY_SCHEDULE.strip() in block
        assert "De madrugada" in block