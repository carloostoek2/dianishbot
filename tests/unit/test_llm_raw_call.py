"""HTTP-level tests for services.llm.raw_call (aiohttp mocked)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services import llm as llm_mod
from services.llm import raw_call


def _mock_aiohttp_response(*, status: int = 200, json_data=None, text: str = ""):
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value=text)
    resp.json = AsyncMock(return_value=json_data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


def _mock_aiohttp_session(post_return):
    session = AsyncMock()
    session.post = MagicMock(return_value=post_return)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.mark.asyncio
async def test_raw_call_deepseek_returns_content_on_200():
    payload = {
        "choices": [{"message": {"content": '  {"response": "hola"}  '}}],
    }
    resp = _mock_aiohttp_response(status=200, json_data=payload)
    session = _mock_aiohttp_session(resp)

    with patch("services.llm_settings.get_provider", return_value="deepseek"), \
         patch("services.llm_settings.get_model", return_value="deepseek-v4-pro"), \
         patch("services.llm.aiohttp.ClientSession", return_value=session):
        content, err, detail = await raw_call([{"role": "user", "content": "hola"}])

    assert content == '{"response": "hola"}'
    assert err is None
    assert detail is None
    session.post.assert_called_once()
    assert session.post.call_args.args[0] == llm_mod.DEEPSEEK_URL
    headers = session.post.call_args.kwargs["headers"]
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["Content-Type"] == "application/json"
    body = session.post.call_args.kwargs["json"]
    assert body["model"] == "deepseek-v4-pro"


@pytest.mark.asyncio
async def test_raw_call_deepseek_returns_none_on_http_error_status():
    resp = _mock_aiohttp_response(status=503, text="service unavailable")
    session = _mock_aiohttp_session(resp)

    with patch("services.llm_settings.get_provider", return_value="deepseek"), \
         patch("services.llm_settings.get_model", return_value="deepseek-v4-pro"), \
         patch("services.llm.aiohttp.ClientSession", return_value=session):
        content, err, detail = await raw_call([{"role": "user", "content": "hola"}])

    assert content is None
    assert err == "error_http_api"
    assert "service unavailable" in detail
    assert session.post.call_args.args[0] == llm_mod.DEEPSEEK_URL
    headers = session.post.call_args.kwargs["headers"]
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_raw_call_deepseek_returns_none_on_network_exception():
    session = AsyncMock()
    session.post = MagicMock(side_effect=TimeoutError("timed out"))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with patch("services.llm_settings.get_provider", return_value="deepseek"), \
         patch("services.llm_settings.get_model", return_value="deepseek-v4-pro"), \
         patch("services.llm.aiohttp.ClientSession", return_value=session):
        content, err, detail = await raw_call([{"role": "user", "content": "hola"}])

    assert content is None
    assert err == "error_red"
    assert "timed out" in detail
    assert session.post.call_args.args[0] == llm_mod.DEEPSEEK_URL
    headers = session.post.call_args.kwargs["headers"]
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_raw_call_deepseek_empty_content_returns_api_detail():
    payload = {
        "choices": [{
            "finish_reason": "content_filter",
            "message": {
                "content": "",
                "reasoning_content": "<|begin▁of▁thinking|>solo interno<|end▁of▁thinking|>",
            },
        }],
        "usage": {"prompt_tokens": 120, "completion_tokens": 0},
    }
    resp = _mock_aiohttp_response(status=200, json_data=payload)
    session = _mock_aiohttp_session(resp)

    with patch("services.llm_settings.get_provider", return_value="deepseek"), \
         patch("services.llm_settings.get_model", return_value="deepseek-v4-flash"), \
         patch("services.llm.aiohttp.ClientSession", return_value=session):
        content, err, detail = await raw_call([{"role": "user", "content": "hola"}])

    assert content is None
    assert err == "api_respuesta_vacia"
    assert "finish_reason=content_filter" in detail
    assert "reasoning_content=" in detail
    assert "deepseek-v4-flash" in detail


@pytest.mark.asyncio
async def test_raw_call_deepseek_recovers_from_reasoning_content():
    payload = {
        "choices": [{
            "finish_reason": "stop",
            "message": {
                "content": "",
                "reasoning_content": (
                    '{"response": "hey que onda", "confidence": 85, "topic": "saludo"}'
                ),
            },
        }],
    }
    resp = _mock_aiohttp_response(status=200, json_data=payload)
    session = _mock_aiohttp_session(resp)

    with patch("services.llm_settings.get_provider", return_value="deepseek"), \
         patch("services.llm_settings.get_model", return_value="deepseek-v4-flash"), \
         patch("services.llm.aiohttp.ClientSession", return_value=session):
        content, err, detail = await raw_call([{"role": "user", "content": "hola"}])

    assert err is None
    assert detail is None
    assert '"response": "hey que onda"' in content


@pytest.mark.asyncio
async def test_raw_call_anthropic_returns_content_on_200():
    payload = {
        "content": [{"type": "text", "text": '{"response": "hola"}'}],
    }
    resp = _mock_aiohttp_response(status=200, json_data=payload)
    session = _mock_aiohttp_session(resp)

    with patch("services.llm_settings.get_provider", return_value="anthropic"), \
         patch("services.llm_settings.get_model", return_value="claude-haiku-4-5-20251001"), \
         patch("services.llm.aiohttp.ClientSession", return_value=session):
        content, err, detail = await raw_call(
            [
                {"role": "system", "content": "Eres Diana"},
                {"role": "user", "content": "hola"},
            ],
            response_format={"type": "json_object", "schema": llm_mod.DIANA_RESPONSE_SCHEMA},
        )

    assert content == '{"response": "hola"}'
    assert err is None
    assert detail is None
    session.post.assert_called_once()
    call_kwargs = session.post.call_args.kwargs
    body = call_kwargs["json"]
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["system"] == "Eres Diana"
    assert body["messages"] == [{"role": "user", "content": "hola"}]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert session.post.call_args.args[0] == llm_mod.ANTHROPIC_URL
    assert call_kwargs["headers"]["x-api-key"] is not None
    assert call_kwargs["headers"]["anthropic-version"] == llm_mod.ANTHROPIC_VERSION
    assert call_kwargs["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_raw_call_anthropic_returns_none_on_http_error_status():
    resp = _mock_aiohttp_response(status=401, text="unauthorized")
    session = _mock_aiohttp_session(resp)

    with patch("services.llm_settings.get_provider", return_value="anthropic"), \
         patch("services.llm_settings.get_model", return_value="claude-haiku-4-5-20251001"), \
         patch("services.llm.aiohttp.ClientSession", return_value=session):
        content, err, detail = await raw_call([{"role": "user", "content": "hola"}])

    assert content is None
    assert err == "error_http_api"
    assert "unauthorized" in detail
    assert session.post.call_args.args[0] == llm_mod.ANTHROPIC_URL
    headers = session.post.call_args.kwargs["headers"]
    assert headers["x-api-key"] is not None
    assert headers["anthropic-version"] == llm_mod.ANTHROPIC_VERSION
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_raw_call_reads_model_each_invocation():
    """Second raw_call uses updated get_model return (hot-reload)."""
    payload = {
        "choices": [{"message": {"content": '{"response": "ok"}'}}],
    }
    resp = _mock_aiohttp_response(status=200, json_data=payload)
    session = _mock_aiohttp_session(resp)

    models = iter(["deepseek-v4-pro", "deepseek-v4-flash"])

    with patch("services.llm_settings.get_provider", return_value="deepseek"), \
         patch("services.llm_settings.get_model", side_effect=lambda: next(models)), \
         patch("services.llm.aiohttp.ClientSession", return_value=session):
        await raw_call([{"role": "user", "content": "hola"}])
        await raw_call([{"role": "user", "content": "hola"}])

    first_model = session.post.call_args_list[0].kwargs["json"]["model"]
    second_model = session.post.call_args_list[1].kwargs["json"]["model"]
    assert first_model == "deepseek-v4-pro"
    assert second_model == "deepseek-v4-flash"