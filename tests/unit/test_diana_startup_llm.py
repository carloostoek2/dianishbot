"""Startup key validation against runtime LLM provider."""

import pytest
from unittest.mock import MagicMock, patch


def test_main_exits_when_runtime_provider_key_missing(monkeypatch):
    import diana

    monkeypatch.setattr(diana, "BOT_TOKEN", "token")
    monkeypatch.setattr(diana, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(diana, "DEEPSEEK_KEY", "ds-key")

    with patch.object(diana.llm_settings, "init"), \
         patch.object(diana.llm_settings, "get_provider", return_value="anthropic"):
        with pytest.raises(SystemExit, match="ANTHROPIC_KEY"):
            diana.main()


def test_main_passes_key_check_when_runtime_key_present(monkeypatch):
    import diana
    import services.chat_history as chat_history_mod
    import services.promo_info as promo_info_mod
    import services.training as training_mod

    monkeypatch.setattr(diana, "BOT_TOKEN", "token")
    monkeypatch.setattr(diana, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(diana, "DEEPSEEK_KEY", "ds-key")

    mock_app = MagicMock()
    mock_db = MagicMock(name="training_db")
    old_dbs = (training_mod.db, chat_history_mod.db, promo_info_mod.db)
    wired = {}

    with patch.object(diana.llm_settings, "init"), \
         patch.object(diana.llm_settings, "get_provider", return_value="deepseek"), \
         patch.object(diana.llm_settings, "get_display_label", return_value="DeepSeek / deepseek-v4-pro"), \
         patch.object(diana, "init_db") as mock_init_db, \
         patch.object(diana.Application, "builder") as mock_builder:
        mock_init_db.return_value = mock_db
        builder = MagicMock()
        mock_builder.return_value = builder
        for method in (
            "token", "post_init", "connect_timeout", "read_timeout", "write_timeout",
            "pool_timeout", "get_updates_connect_timeout", "get_updates_read_timeout",
            "get_updates_write_timeout", "get_updates_pool_timeout",
        ):
            getattr(builder, method).return_value = builder
        builder.build.return_value = mock_app

        try:
            diana.main()
            wired["promo"] = promo_info_mod.db
            wired["chat_history"] = chat_history_mod.db
            wired["training"] = training_mod.db
        finally:
            training_mod.db, chat_history_mod.db, promo_info_mod.db = old_dbs

    mock_init_db.assert_called_once()
    mock_app.run_polling.assert_called_once()
    assert wired["promo"] is mock_db
    assert wired["chat_history"] is mock_db
    assert wired["training"] is mock_db