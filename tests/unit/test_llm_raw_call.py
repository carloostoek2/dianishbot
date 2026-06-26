"""HTTP-level tests for services.llm.raw_call (aiohttp mocked)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
async def test_raw_call_returns_content_on_200():
    payload = {
        "choices": [{"message": {"content": '  {"response": "hola"}  '}}],
    }
    resp = _mock_aiohttp_response(status=200, json_data=payload)
    session = _mock_aiohttp_session(resp)

    with patch("services.llm.aiohttp.ClientSession", return_value=session):
        result = await raw_call([{"role": "user", "content": "hola"}])

    assert result == '{"response": "hola"}'
    session.post.assert_called_once()


@pytest.mark.asyncio
async def test_raw_call_returns_none_on_http_error_status():
    resp = _mock_aiohttp_response(status=503, text="service unavailable")
    session = _mock_aiohttp_session(resp)

    with patch("services.llm.aiohttp.ClientSession", return_value=session):
        result = await raw_call([{"role": "user", "content": "hola"}])

    assert result is None


@pytest.mark.asyncio
async def test_raw_call_returns_none_on_network_exception():
    session = AsyncMock()
    session.post = MagicMock(side_effect=TimeoutError("timed out"))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with patch("services.llm.aiohttp.ClientSession", return_value=session):
        result = await raw_call([{"role": "user", "content": "hola"}])

    assert result is None