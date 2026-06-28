"""Tests for admin LLM selector callbacks (au:llm)."""

import pytest
from unittest.mock import patch

import auth_users
from services import llm_settings


ADMIN_ID = 555002
NON_ADMIN_ID = 999001


@pytest.fixture(autouse=True)
def _configure_admin_and_llm(tmp_path):
    users_file = tmp_path / "authorized.json"
    llm_file = tmp_path / "llm.json"
    auth_users.configure(users_file=str(users_file), max_users=5, seed_user_ids=[])
    auth_users.set_admin_id(ADMIN_ID)
    llm_settings.configure(settings_file=str(llm_file))
    yield


@pytest.fixture
def admin_user(make_user):
    return make_user(user_id=ADMIN_ID, username="diana_admin", first_name="Diana")


def _provider_has_key(provider: str) -> bool:
    return provider == "deepseek"


@pytest.mark.asyncio
async def test_au_llm_menu_renders(make_mock_callback_update, make_context, admin_user):
    with patch.object(llm_settings, "has_api_key", side_effect=_provider_has_key):
        update = make_mock_callback_update(data="au:llm", user=admin_user)
        result = await auth_users.handle_callback(update, make_context())

    assert result is True
    update.callback_query.edit_message_text.assert_awaited_once()
    text = update.callback_query.edit_message_text.await_args[0][0]
    kwargs = update.callback_query.edit_message_text.await_args[1]
    assert "Configuración LLM" in text
    markup = kwargs["reply_markup"]
    callbacks = [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
    ]
    labels = [
        btn.text
        for row in markup.inline_keyboard
        for btn in row
    ]
    assert "au:llm_set:provider:deepseek" in callbacks
    assert "au:llm:nokey" in callbacks
    assert any("(sin key)" in label for label in labels)
    assert any(cb.startswith("au:llm_set:model:") for cb in callbacks)


@pytest.mark.asyncio
async def test_au_llm_set_provider_updates(make_mock_callback_update, make_context, admin_user):
    with patch.object(llm_settings, "has_api_key", return_value=True):
        update = make_mock_callback_update(
            data="au:llm_set:provider:anthropic",
            user=admin_user,
        )
        result = await auth_users.handle_callback(update, make_context())

    assert result is True
    assert llm_settings.get_provider() == "anthropic"
    update.callback_query.answer.assert_awaited_with("Proveedor actualizado")


@pytest.mark.asyncio
async def test_au_llm_set_provider_success_toast(make_mock_callback_update, make_context, admin_user):
    with patch.object(llm_settings, "has_api_key", return_value=True):
        update = make_mock_callback_update(
            data="au:llm_set:provider:deepseek",
            user=admin_user,
        )
        await auth_users.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited_with("Proveedor actualizado")


@pytest.mark.asyncio
async def test_au_llm_set_model_success_toast(make_mock_callback_update, make_context, admin_user):
    with patch.object(llm_settings, "has_api_key", return_value=True):
        llm_settings.set_provider("deepseek")
        update = make_mock_callback_update(
            data="au:llm_set:model:deepseek-v4-flash",
            user=admin_user,
        )
        await auth_users.handle_callback(update, make_context())

    update.callback_query.answer.assert_awaited_with("Modelo actualizado")


@pytest.mark.asyncio
async def test_au_llm_menu_refresh_after_model_set(make_mock_callback_update, make_context, admin_user):
    with patch.object(llm_settings, "has_api_key", return_value=True):
        llm_settings.set_provider("deepseek")
        update = make_mock_callback_update(
            data="au:llm_set:model:deepseek-v4-flash",
            user=admin_user,
        )
        await auth_users.handle_callback(update, make_context())

    assert update.callback_query.edit_message_text.await_count == 1
    refreshed_text = update.callback_query.edit_message_text.await_args[0][0]
    assert "deepseek-v4-flash" in refreshed_text
    markup = update.callback_query.edit_message_text.await_args[1]["reply_markup"]
    model_labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("deepseek-v4-flash ✅" in label for label in model_labels)


@pytest.mark.asyncio
async def test_au_llm_set_provider_refused_no_key(make_mock_callback_update, make_context, admin_user):
    original = llm_settings.get_provider()

    with patch.object(llm_settings, "has_api_key", return_value=False):
        update = make_mock_callback_update(
            data="au:llm_set:provider:anthropic",
            user=admin_user,
        )
        result = await auth_users.handle_callback(update, make_context())

    assert result is True
    assert llm_settings.get_provider() == original
    update.callback_query.answer.assert_awaited_with(
        "Falta API key en .env",
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_au_llm_set_model_updates(make_mock_callback_update, make_context, admin_user):
    with patch.object(llm_settings, "has_api_key", return_value=True):
        llm_settings.set_provider("deepseek")
        update = make_mock_callback_update(
            data="au:llm_set:model:deepseek-v4-flash",
            user=admin_user,
        )
        result = await auth_users.handle_callback(update, make_context())

    assert result is True
    assert llm_settings.get_model() == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_au_llm_non_admin_rejected(make_mock_callback_update, make_context, make_user):
    outsider = make_user(user_id=NON_ADMIN_ID)
    update = make_mock_callback_update(data="au:llm", user=outsider)

    result = await auth_users.handle_callback(update, make_context())

    assert result is True
    update.callback_query.answer.assert_awaited_with("No autorizado", show_alert=True)
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_au_llm_set_non_admin_rejected(make_mock_callback_update, make_context, make_user):
    outsider = make_user(user_id=NON_ADMIN_ID)
    update = make_mock_callback_update(
        data="au:llm_set:provider:anthropic",
        user=outsider,
    )

    result = await auth_users.handle_callback(update, make_context())

    assert result is True
    update.callback_query.answer.assert_awaited_with("No autorizado", show_alert=True)
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_au_llm_set_malformed_callback_too_short(make_mock_callback_update, make_context, admin_user):
    update = make_mock_callback_update(data="au:llm_set:provider", user=admin_user)

    result = await auth_users.handle_callback(update, make_context())

    assert result is True
    update.callback_query.answer.assert_awaited_with(
        "Callback LLM inválido",
        show_alert=True,
    )
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_au_llm_set_unknown_sub_action(make_mock_callback_update, make_context, admin_user):
    update = make_mock_callback_update(data="au:llm_set:foo:bar", user=admin_user)

    result = await auth_users.handle_callback(update, make_context())

    assert result is True
    update.callback_query.answer.assert_awaited_with(
        "Acción LLM desconocida",
        show_alert=True,
    )
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_au_llm_set_invalid_provider_callback(make_mock_callback_update, make_context, admin_user):
    original = llm_settings.get_provider()
    update = make_mock_callback_update(
        data="au:llm_set:provider:openai",
        user=admin_user,
    )

    result = await auth_users.handle_callback(update, make_context())

    assert result is True
    assert llm_settings.get_provider() == original
    update.callback_query.answer.assert_awaited_with(
        "Proveedor inválido",
        show_alert=True,
    )
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_au_llm_set_invalid_model_callback(make_mock_callback_update, make_context, admin_user):
    with patch.object(llm_settings, "has_api_key", return_value=True):
        original_model = llm_settings.get_model()
        update = make_mock_callback_update(
            data="au:llm_set:model:deepseek-chat",
            user=admin_user,
        )
        result = await auth_users.handle_callback(update, make_context())

    assert result is True
    assert llm_settings.get_model() == original_model
    update.callback_query.answer.assert_awaited_with(
        "Modelo no permitido",
        show_alert=True,
    )
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_au_llm_set_model_refused_no_key(make_mock_callback_update, make_context, admin_user):
    original_model = llm_settings.get_model()

    with patch.object(llm_settings, "has_api_key", return_value=False):
        update = make_mock_callback_update(
            data="au:llm_set:model:deepseek-v4-flash",
            user=admin_user,
        )
        result = await auth_users.handle_callback(update, make_context())

    assert result is True
    assert llm_settings.get_model() == original_model
    update.callback_query.answer.assert_awaited_with(
        "Falta API key en .env",
        show_alert=True,
    )
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_au_llm_set_save_failure_alert(make_mock_callback_update, make_context, admin_user):
    with patch.object(llm_settings, "has_api_key", return_value=True):
        llm_settings.set_provider("deepseek")

    with patch.object(llm_settings, "has_api_key", return_value=True), \
         patch("services.llm_settings.os.replace", side_effect=OSError("disk full")):
        update = make_mock_callback_update(
            data="au:llm_set:model:deepseek-v4-flash",
            user=admin_user,
        )
        result = await auth_users.handle_callback(update, make_context())

    assert result is True
    update.callback_query.answer.assert_awaited_with(
        "Error guardando configuración",
        show_alert=True,
    )
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_au_llm_nokey_callback_alerts(make_mock_callback_update, make_context, admin_user):
    update = make_mock_callback_update(data="au:llm:nokey", user=admin_user)

    result = await auth_users.handle_callback(update, make_context())

    assert result is True
    update.callback_query.answer.assert_awaited_with(
        "Falta API key en .env",
        show_alert=True,
    )


def test_callback_data_lengths():
    callbacks = [
        "au:llm",
        "au:llm:nokey",
        "au:llm_set:provider:deepseek",
        "au:llm_set:provider:anthropic",
        "au:llm_set:model:deepseek-v4-flash",
        "au:llm_set:model:claude-haiku-4-5-20251001",
        "au:llm_set:model:claude-sonnet-4-6",
        "au:llm_set:model:claude-opus-4-8",
    ]
    for cb in callbacks:
        assert len(cb.encode("utf-8")) <= 64, cb