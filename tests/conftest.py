"""Run tests against Home Assistant itself, with an isolated config directory."""

import aiohttp
import pytest
from homeassistant import config_entries, loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame


@pytest.fixture
async def hass(tmp_path, monkeypatch):
    instance = HomeAssistant(str(tmp_path))
    loader.async_setup(instance)
    frame.async_setup(instance)
    instance.config_entries = config_entries.ConfigEntries(instance, {})
    await async_load_base_functionality(instance)
    await instance.config_entries.async_initialize()
    # Isolate HA mDNS/DNS infrastructure while exercising actual HTTP transport.
    async with aiohttp.ClientSession() as session:
        monkeypatch.setattr(
            "custom_components.ha_decisions.sensor.async_get_clientsession", lambda hass: session
        )
        yield instance
    for entry in instance.config_entries.async_entries():
        if entry.state is config_entries.ConfigEntryState.LOADED:
            await instance.config_entries.async_unload(entry.entry_id)
    await instance.async_stop(force=True)


@pytest.fixture
def cfg():
    from custom_components.ha_decisions.model import effective_config

    return effective_config(
        {
            "name": "Battery decision",
            "api_url": "http://127.0.0.1:8000/v1/systemone",
            "references": ["sensor.battery"],
        }
    )


@pytest.fixture
async def http_server():
    from aiohttp import web

    runners = []

    async def start(handler):
        app = web.Application()
        app.router.add_post("/endpoint", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        port = site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}/endpoint"

    yield start
    for runner in runners:
        await runner.cleanup()
