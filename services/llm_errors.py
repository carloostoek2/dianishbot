"""Leaf module: LLM failure codes and human-readable labels (no llm/training imports)."""

FAIL_NO_HISTORY = "sin_historial"
FAIL_ABORTED = "cancelado_mensaje_nuevo"
FAIL_HTTP = "error_http_api"
FAIL_NETWORK = "error_red"
FAIL_EMPTY_API = "api_respuesta_vacia"
FAIL_INVALID_JSON = "json_invalido"
FAIL_EMPTY_RESPONSE = "campo_response_vacio"
FAIL_EXHAUSTED = "reintentos_agotados"

_REASON_LABELS = {
    FAIL_NO_HISTORY: "sin mensajes en el historial",
    FAIL_ABORTED: "cancelado (llegó un mensaje nuevo)",
    FAIL_HTTP: "error HTTP de la API del LLM",
    FAIL_NETWORK: "error de red o timeout",
    FAIL_EMPTY_API: "el LLM devolvió contenido vacío",
    FAIL_INVALID_JSON: "respuesta no es JSON válido",
    FAIL_EMPTY_RESPONSE: "JSON válido pero campo response vacío",
    FAIL_EXHAUSTED: "agotados los reintentos",
}


def failure_label(reason: str) -> str:
    return _REASON_LABELS.get(reason, reason)