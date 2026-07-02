"""Tests for services/llm_errors.py (leaf module, no circular imports)."""

import importlib
import importlib.util
import sys

import pytest

from services import llm_errors
from services.llm_errors import (
    FAIL_ABORTED,
    FAIL_EMPTY_API,
    FAIL_EMPTY_RESPONSE,
    FAIL_EXHAUSTED,
    FAIL_HTTP,
    FAIL_INVALID_JSON,
    FAIL_NETWORK,
    FAIL_NO_HISTORY,
    failure_label,
)


def test_all_fail_constants_present():
    expected = {
        "sin_historial",
        "cancelado_mensaje_nuevo",
        "error_http_api",
        "error_red",
        "api_respuesta_vacia",
        "json_invalido",
        "campo_response_vacio",
        "reintentos_agotados",
    }
    actual = {
        FAIL_NO_HISTORY,
        FAIL_ABORTED,
        FAIL_HTTP,
        FAIL_NETWORK,
        FAIL_EMPTY_API,
        FAIL_INVALID_JSON,
        FAIL_EMPTY_RESPONSE,
        FAIL_EXHAUSTED,
    }
    assert actual == expected


@pytest.mark.parametrize(
    "reason,label",
    [
        (FAIL_NO_HISTORY, "sin mensajes en el historial"),
        (FAIL_ABORTED, "cancelado (llegó un mensaje nuevo)"),
        (FAIL_HTTP, "error HTTP de la API del LLM"),
        (FAIL_NETWORK, "error de red o timeout"),
        (FAIL_EMPTY_API, "el LLM devolvió contenido vacío"),
        (FAIL_INVALID_JSON, "respuesta no es JSON válido"),
        (FAIL_EMPTY_RESPONSE, "JSON válido pero campo response vacío"),
        (FAIL_EXHAUSTED, "agotados los reintentos"),
    ],
)
def test_failure_label_known(reason, label):
    assert failure_label(reason) == label


def test_failure_label_unknown_passthrough():
    assert failure_label("custom_reason") == "custom_reason"


def test_leaf_module_no_llm_or_training_imports():
    """llm_errors must not import services.llm or services.training."""
    source = importlib.util.find_spec("services.llm_errors")
    assert source is not None
    # Reload from scratch to inspect module attributes
    mod = sys.modules.get("services.llm_errors")
    assert mod is llm_errors
    for name in dir(llm_errors):
        if name.startswith("_"):
            continue
    # Static check: module file has no forbidden imports
    path = importlib.util.find_spec("services.llm_errors").origin
    text = open(path, encoding="utf-8").read()
    assert "services.llm" not in text
    assert "services.training" not in text


def test_llm_reexports_failure_label_and_fail_constants():
    from services.llm import FAIL_ABORTED, FAIL_HTTP, failure_label as llm_failure_label

    assert llm_failure_label(FAIL_HTTP) == failure_label(FAIL_HTTP)
    assert FAIL_ABORTED == "cancelado_mensaje_nuevo"