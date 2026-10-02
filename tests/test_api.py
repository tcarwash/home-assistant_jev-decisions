import asyncio

import aiohttp
import pytest
from aiohttp import web

from custom_components.ha_decisions.api import DecisionError, async_request


async def test_real_http_payload_and_auth(cfg, http_server):
    async def handler(request):
        assert request.headers["Authorization"] == "Bearer test-key"
        data = await request.json()
        assert data["model"] == "typed-decisions"
        assert data["state"] == {"sensor.battery": {"state": "20"}}
        return web.json_response({"answers": {"decision": {"choice": "yes", "confidence": 0.9}}})

    cfg.update(api_url=await http_server(handler), api_key="test-key")
    async with aiohttp.ClientSession() as session:
        answers = await async_request(session, cfg, {"sensor.battery": {"state": "20"}})
    assert answers["decision"]["choice"] == "yes"


@pytest.mark.parametrize("status", [302, 401, 429, 500])
async def test_http_errors_redact_bodies(cfg, http_server, status):
    async def handler(request):
        return web.Response(
            status=status, text="PRIVATE MODEL OUTPUT test-key", headers={"Location": "/endpoint"}
        )

    cfg.update(api_url=await http_server(handler), api_key="test-key")
    async with aiohttp.ClientSession() as session:
        with pytest.raises(DecisionError) as err:
            await async_request(session, cfg, {})
    assert err.value.http_status == status
    assert "PRIVATE" not in str(err.value) and "test-key" not in str(err.value)


@pytest.mark.parametrize(
    "body,code",
    [
        ("not json", "invalid_response"),
        ('{"answers":{}}', "invalid_response"),
        ("x" * (1024 * 1024 + 1), "response_too_large"),
    ],
)
async def test_bad_response(cfg, http_server, body, code):
    async def handler(request):
        return web.Response(text=body)

    cfg["api_url"] = await http_server(handler)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(DecisionError) as err:
            await async_request(session, cfg, {})
    assert err.value.code == code


async def test_timeout(cfg, http_server):
    async def handler(request):
        await asyncio.sleep(0.1)
        return web.json_response({})

    cfg.update(api_url=await http_server(handler), timeout=0.01)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(DecisionError) as err:
            await async_request(session, cfg, {})
    assert err.value.code == "timeout"


async def test_real_chat_completions(cfg, http_server):
    import json

    async def handler(request):
        payload = await request.json()
        assert "state" not in payload
        context = json.loads(payload["messages"][1]["content"])
        assert context["questions"]["decision"]["type"] == "noul"
        return web.json_response(
            {
                "choices": [
                    {"message": {"content": json.dumps({"answers": {"decision": {"noul": 0.88}}})}}
                ]
            }
        )

    cfg.update(
        api_url=await http_server(handler),
        backend="openai_compatible",
        questions={"decision": {"type": "noul"}},
    )
    async with aiohttp.ClientSession() as session:
        result = await async_request(session, cfg, {})
    assert result["decision"]["noul"] == 0.88


async def test_unreachable_server(cfg):
    # Bind an unused ephemeral port, then release it before asking.
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    cfg["api_url"] = f"http://127.0.0.1:{port}/endpoint"
    async with aiohttp.ClientSession() as session:
        with pytest.raises(DecisionError) as err:
            await async_request(session, cfg, {})
    assert err.value.code == "connection_error"
