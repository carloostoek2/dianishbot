"""Pure logic tests extracted from handlers/business.py (no Telegram)."""

import pytest
from config import is_llm_escalation_topic
from handlers.business import needs_escalation


class TestNeedsEscalation:
    @pytest.mark.parametrize(
        "text,should_match",
        [
            ("cuando es el pago?", "Keyword detectada"),
            ("quiero cancelar mi suscripcion", "Keyword detectada"),
            ("hola todo bien", None),
            ("precio del vip?", "Keyword detectada"),
            ("", None),
        ],
    )
    def test_escalation_keywords(self, text, should_match):
        result = needs_escalation(text)
        if should_match:
            assert result is not None
            assert should_match in result
        else:
            assert result is None


class TestIsLlmEscalationTopic:
    @pytest.mark.parametrize(
        "topic,expected",
        [
            ("escalado_humano", True),
            ("escalado", True),
            ("escalado_crisis", True),
            ("Escalado_Humano", True),
            ("saludo_casual", False),
            ("mapa_del_deseo", False),
            ("", False),
        ],
    )
    def test_llm_escalation_topics(self, topic, expected):
        assert is_llm_escalation_topic(topic) is expected
