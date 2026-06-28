"""Tests for services.llm_settings runtime provider/model persistence."""

import json
import stat
from unittest.mock import patch

import config
import pytest
from services import llm_settings


def _configure(tmp_path, **kwargs):
    settings_file = tmp_path / "llm.json"
    llm_settings.configure(settings_file=str(settings_file), **kwargs)
    return settings_file


def test_seed_when_file_missing(tmp_path):
    path = _configure(tmp_path)
    assert path.exists()
    assert llm_settings.get_provider() == config.LLM_PROVIDER.strip().lower() or "deepseek"
    assert llm_settings.get_model() in llm_settings.MODEL_CATALOG[llm_settings.get_provider()]


def test_round_trip_save_load(tmp_path):
    path = _configure(tmp_path)

    with patch.object(llm_settings, "has_api_key", return_value=True):
        ok, err = llm_settings.set_provider("deepseek")
        assert ok and err is None
        ok, err = llm_settings.set_model("deepseek-v4-flash")
        assert ok and err is None
        ok, err = llm_settings.set_provider("anthropic")
        assert ok and err is None

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["provider"] == "anthropic"
    assert data["models"]["deepseek"] == "deepseek-v4-flash"

    llm_settings.configure(settings_file=str(path))
    assert llm_settings.get_provider() == "anthropic"
    assert llm_settings.get_model() == llm_settings.DEFAULT_MODELS["anthropic"]


def test_rejects_excluded_deepseek_chat(tmp_path):
    _configure(tmp_path)
    with patch.object(llm_settings, "has_api_key", return_value=True):
        ok, err = llm_settings.set_model("deepseek-chat")
    assert ok is False
    assert err == "Modelo no permitido"


def test_provider_switch_restores_per_provider_model(tmp_path):
    _configure(tmp_path)

    with patch.object(llm_settings, "has_api_key", return_value=True):
        ok, _ = llm_settings.set_provider("anthropic")
        assert ok
        ok, _ = llm_settings.set_model("claude-sonnet-4-6")
        assert ok

        ok, _ = llm_settings.set_provider("deepseek")
        assert ok
        ok, _ = llm_settings.set_model("deepseek-v4-flash")
        assert ok

        ok, _ = llm_settings.set_provider("anthropic")
        assert ok

    assert llm_settings.get_provider() == "anthropic"
    assert llm_settings.get_model() == "claude-sonnet-4-6"


def test_set_provider_refuses_missing_key(tmp_path):
    _configure(tmp_path)
    original = llm_settings.get_provider()

    with patch.object(llm_settings, "has_api_key", return_value=False):
        ok, err = llm_settings.set_provider("anthropic")

    assert ok is False
    assert err == "Falta API key en .env"
    assert llm_settings.get_provider() == original


def test_corrupt_json_falls_back(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text("{not valid json", encoding="utf-8")
    llm_settings.configure(settings_file=str(path))

    assert llm_settings.get_provider() in llm_settings.MODEL_CATALOG
    assert llm_settings.get_model() in llm_settings.MODEL_CATALOG[llm_settings.get_provider()]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "provider" in data
    assert "models" in data


def test_invalid_model_in_json_clamped(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text(
        json.dumps({
            "provider": "deepseek",
            "models": {
                "deepseek": "deepseek-chat",
                "anthropic": "claude-haiku-4-5-20251001",
            },
        }),
        encoding="utf-8",
    )
    llm_settings.configure(settings_file=str(path))

    assert llm_settings.get_model() == llm_settings.DEFAULT_MODELS["deepseek"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["models"]["deepseek"] == llm_settings.DEFAULT_MODELS["deepseek"]


def test_legacy_single_model_migrates(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text(
        json.dumps({"provider": "deepseek", "model": "deepseek-v4-flash"}),
        encoding="utf-8",
    )
    llm_settings.configure(settings_file=str(path))

    assert llm_settings.get_provider() == "deepseek"
    assert llm_settings.get_model() == "deepseek-v4-flash"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "models" in data
    assert data["models"]["deepseek"] == "deepseek-v4-flash"


def test_get_display_label(tmp_path):
    _configure(tmp_path)
    label = llm_settings.get_display_label()
    assert "DeepSeek" in label or "Anthropic" in label
    assert "/" in label
    assert llm_settings.get_model() in label


def test_init_idempotent(tmp_path):
    path = tmp_path / "llm.json"
    with patch.object(config, "LLM_SETTINGS_FILE", str(path)):
        llm_settings.init()
        provider1 = llm_settings.get_provider()
        llm_settings.init()
        assert llm_settings.get_provider() == provider1


def test_set_provider_invalid_provider(tmp_path):
    _configure(tmp_path)
    original = llm_settings.get_provider()

    ok, err = llm_settings.set_provider("openai")

    assert ok is False
    assert err == "Proveedor inválido"
    assert llm_settings.get_provider() == original


def test_set_model_refuses_missing_key(tmp_path):
    _configure(tmp_path)
    original_model = llm_settings.get_model()

    with patch.object(llm_settings, "has_api_key", return_value=False):
        ok, err = llm_settings.set_model("deepseek-v4-flash")

    assert ok is False
    assert err == "Falta API key en .env"
    assert llm_settings.get_model() == original_model


def test_save_strips_extra_json_keys(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text(
        json.dumps({
            "provider": "deepseek",
            "models": {"deepseek": "deepseek-v4-pro", "anthropic": "claude-haiku-4-5-20251001"},
            "api_key": "secret",
            "model": "legacy",
        }),
        encoding="utf-8",
    )
    llm_settings.configure(settings_file=str(path))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"provider", "models"}
    assert "api_key" not in data
    assert "model" not in data


def test_save_failure_does_not_mutate_state_on_set_provider(tmp_path):
    _configure(tmp_path)
    original_provider = llm_settings.get_provider()
    original_models = dict(llm_settings._state.get("models", {}))

    with patch("services.llm_settings.os.replace", side_effect=OSError("disk full")):
        with patch.object(llm_settings, "has_api_key", return_value=True):
            ok, err = llm_settings.set_provider("anthropic")

    assert ok is False
    assert err == "Error guardando configuración"
    assert llm_settings.get_provider() == original_provider
    assert llm_settings._state.get("models") == original_models


def test_save_failure_does_not_mutate_state_on_set_model(tmp_path):
    _configure(tmp_path)
    with patch.object(llm_settings, "has_api_key", return_value=True):
        llm_settings.set_provider("deepseek")

    original_model = llm_settings.get_model()
    original_models = dict(llm_settings._state.get("models", {}))

    with patch("services.llm_settings.os.replace", side_effect=OSError("disk full")):
        with patch.object(llm_settings, "has_api_key", return_value=True):
            ok, err = llm_settings.set_model("deepseek-v4-flash")

    assert ok is False
    assert err == "Error guardando configuración"
    assert llm_settings.get_model() == original_model
    assert llm_settings._state.get("models") == original_models


def test_save_sets_file_permissions(tmp_path):
    path = _configure(tmp_path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_has_api_key_reads_real_config(tmp_path):
    _configure(tmp_path)
    with patch.object(llm_settings, "DEEPSEEK_KEY", "ds-key"), \
         patch.object(llm_settings, "ANTHROPIC_KEY", ""):
        assert llm_settings.has_api_key("deepseek") is True
        assert llm_settings.has_api_key("anthropic") is False


def test_load_warns_missing_active_key(tmp_path, caplog):
    path = tmp_path / "llm.json"
    path.write_text(
        json.dumps({
            "provider": "anthropic",
            "models": {
                "deepseek": "deepseek-v4-pro",
                "anthropic": "claude-haiku-4-5-20251001",
            },
        }),
        encoding="utf-8",
    )
    with patch.object(llm_settings, "ANTHROPIC_KEY", ""), \
         patch.object(llm_settings, "DEEPSEEK_KEY", "ds-key"):
        with caplog.at_level("WARNING"):
            llm_settings.configure(settings_file=str(path))

    assert any("sin API key" in rec.message for rec in caplog.records)