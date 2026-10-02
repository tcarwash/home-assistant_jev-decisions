import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
from homeassistant.exceptions import ServiceValidationError

from custom_components.ha_decisions.const import DOMAIN


async def add_entry(hass, cfg, entry_id="original-entry"):
    entry = ConfigEntry(
        domain=DOMAIN,
        title=cfg["name"],
        data=cfg,
        options={},
        source="user",
        unique_id=cfg["name"].lower(),
        version=1,
        minor_version=1,
        entry_id=entry_id,
        discovery_keys={},
        subentries_data=[],
    )
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_setup_service_and_unload(hass, cfg):
    cfg["auto_update"] = False
    entry = await add_entry(hass, cfg)
    entity = next(iter(hass.data[DOMAIN]["entities"].values()))
    assert entity.unique_id == "original-entry"
    assert hass.states.get(entity.entity_id).state == "waiting"
    with patch(
        "custom_components.ha_decisions.sensor.async_request",
        AsyncMock(
            return_value={"decision": {"type": "choice", "choice": "yes", "status": "forged"}}
        ),
    ):
        await hass.services.async_call(
            DOMAIN, "ask", {"entity_id": entity.entity_id}, blocking=True
        )
    state = hass.states.get(entity.entity_id)
    assert state.state == "yes"
    assert state.attributes["status"] == "complete"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "ask", {"entity_id": "sensor.wrong"}, blocking=True)
    await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.data[DOMAIN]["entities"]
    assert not hass.services.has_service(DOMAIN, "ask")


@pytest.mark.parametrize(
    "kind,fields",
    [
        ("choice", {"criteria": "yes: yes\nno: no"}),
        ("score", {"criteria": "Low\nMedium\nHigh"}),
        ("noul", {"true_description": "Needs charging", "false_description": "Does not"}),
    ],
)
async def test_guided_config_and_options(hass, cfg, kind, fields):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {key: cfg[key] for key in ("name", "backend", "api_url", "api_key", "model")},
    )
    assert result["step_id"] == "question_type"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": kind}
    )
    assert result["step_id"] == kind
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "question_key": "battery",
            "instructions": "Needs charging?",
            **fields,
        },
    )
    assert result["step_id"] == "behavior"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "references": ["sensor.battery"],
            "auto_update": False,
            "debounce": 2,
            "scan_interval": 0,
            "timeout": 60,
        },
    )
    assert result["type"] == "create_entry"
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.data["questions"]["battery"]["type"] == kind
    options = await hass.config_entries.options.async_init(entry.entry_id)
    assert options["step_id"] == "init"
    options = await hass.config_entries.options.async_configure(
        options["flow_id"], {"next_step_id": "behavior"}
    )
    options = await hass.config_entries.options.async_configure(
        options["flow_id"],
        {
            "references": [],
            "auto_update": False,
            "debounce": 5,
            "scan_interval": 0,
            "timeout": 30,
        },
    )
    assert options["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["questions"]["battery"]["type"] == kind
    assert entry.state is ConfigEntryState.LOADED


async def test_startup_changes_coalesced_and_cleanup(hass, cfg):
    cfg.update(debounce=0.01, scan_interval=0)
    entry = await add_entry(hass, cfg)
    entity = next(iter(hass.data[DOMAIN]["entities"].values()))
    calls = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def request(session, config, state):
        calls.append(state)
        if len(calls) == 1:
            started.set()
            await release.wait()
        return {"decision": {"choice": "yes"}}

    with patch("custom_components.ha_decisions.sensor.async_request", request):
        hass.state = CoreState.running
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
        # Advance the real scheduled startup callback without a one-second wait.
        entity._timer.cancel()
        entity._launch()
        await asyncio.wait_for(started.wait(), 2)
        hass.states.async_set("sensor.battery", "20")
        hass.states.async_set("sensor.battery", "21")
        await hass.async_block_till_done()
        await asyncio.sleep(0.03)
        assert len(calls) == 1  # Changing inputs has not cancelled/restarted the active request.
        release.set()
        await asyncio.sleep(0.05)
        assert len(calls) == 2
        assert calls[1]["sensor.battery"]["state"] == "21"
        await hass.config_entries.async_unload(entry.entry_id)
        hass.states.async_set("sensor.battery", "22")
        await asyncio.sleep(0.03)
        assert len(calls) == 2


async def test_multiple_entries_service_lifetime(hass, cfg):
    cfg["auto_update"] = False
    first = await add_entry(hass, cfg, "first")
    second = await add_entry(hass, {**cfg, "name": "Other"}, "second")
    await hass.config_entries.async_unload(first.entry_id)
    assert hass.services.has_service(DOMAIN, "ask")
    await hass.config_entries.async_unload(second.entry_id)
    assert not hass.services.has_service(DOMAIN, "ask")


@pytest.mark.parametrize("kind,value", [("score", 1.75), ("noul", 0.87)])
async def test_sensor_real_http_numeric_state(hass, cfg, http_server, kind, value):
    from aiohttp import web

    async def handler(request):
        data = await request.json()
        assert data["state"]["sensor.battery"]["state"] == "20"
        assert data["questions"]["decision"]["type"] == kind
        return web.json_response({"answers": {"decision": {kind: value, "confidence": 0.9}}})

    cfg.update(
        api_url=await http_server(handler),
        auto_update=False,
        questions={"decision": {"type": kind}},
    )
    hass.states.async_set("sensor.battery", "20")
    await add_entry(hass, cfg)
    entity = next(iter(hass.data[DOMAIN]["entities"].values()))
    await hass.services.async_call(DOMAIN, "ask", {"entity_id": [entity.entity_id]}, blocking=True)
    state = hass.states.get(entity.entity_id)
    assert float(state.state) == value
    assert state.attributes[kind] == value
    assert state.attributes["status"] == "complete"


async def test_error_state_and_safe_diagnostics(hass, cfg):
    from custom_components.ha_decisions.api import DecisionError
    from custom_components.ha_decisions.diagnostics import async_get_config_entry_diagnostics

    cfg.update(
        auto_update=False, api_key="PRIVATE_KEY", api_url="http://private-host:8000/private-url"
    )
    entry = await add_entry(hass, cfg)
    entity = next(iter(hass.data[DOMAIN]["entities"].values()))
    with patch(
        "custom_components.ha_decisions.sensor.async_request",
        AsyncMock(side_effect=DecisionError("http_error", "Endpoint returned HTTP 401", 401)),
    ):
        await entity.async_ask()
    assert hass.states.get(entity.entity_id).state == "error"
    assert entity.extra_state_attributes["http_status"] == 401
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["sensors"][0]["error_type"] == "http_error"
    assert "PRIVATE_KEY" not in str(diagnostics)
    assert "private-host" not in str(diagnostics)
    assert "private-url" not in str(diagnostics)


async def test_advanced_questions_and_errors(hass, cfg):
    import json

    cfg["auto_update"] = False
    entry = await add_entry(hass, cfg)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "question_type"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "advanced"}
    )
    flow_id = result["flow_id"]
    result = await hass.config_entries.options.async_configure(
        flow_id, {"questions": "[]", "primary_question": ""}
    )
    assert result["errors"] == {"questions": "invalid_json"}
    questions = {
        "p": {"type": "noul"},
        "urgency": {"type": "score", "criteria": ["low", "high"]},
        "custom": {"type": "custom", "backend_option": True},
    }
    result = await hass.config_entries.options.async_configure(
        flow_id, {"questions": json.dumps(questions), "primary_question": "wrong"}
    )
    assert result["errors"] == {"primary_question": "invalid_question"}
    result = await hass.config_entries.options.async_configure(
        flow_id, {"questions": json.dumps(questions), "primary_question": "urgency"}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["questions"] == questions
    assert entry.options["primary_question"] == "urgency"


async def test_periodic_refresh_and_cancel_active_request(hass, cfg):
    cfg.update(auto_update=True, scan_interval=60)
    hass.state = CoreState.running
    entry = await add_entry(hass, cfg)
    entity = next(iter(hass.data[DOMAIN]["entities"].values()))
    assert entity._timer is not None
    entity._timer.cancel()
    entity._timer = None
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def request(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with patch("custom_components.ha_decisions.sensor.async_request", request):
        entity._on_interval(None)
        await asyncio.wait_for(started.wait(), 1)
        await hass.config_entries.async_unload(entry.entry_id)
        assert cancelled.is_set()
        assert entity._removed
        assert not entity._tasks


async def test_manual_only_has_no_startup_timer(hass, cfg):
    cfg.update(auto_update=False, scan_interval=60)
    hass.state = CoreState.running
    await add_entry(hass, cfg)
    entity = next(iter(hass.data[DOMAIN]["entities"].values()))
    hass.states.async_set("sensor.battery", "20")
    await hass.async_block_till_done()
    assert entity._timer is None
    assert not entity._tasks


async def test_wait_for_startup_before_state_updates(hass, cfg):
    await add_entry(hass, cfg)
    entity = next(iter(hass.data[DOMAIN]["entities"].values()))
    hass.states.async_set("sensor.battery", "20")
    await hass.async_block_till_done()
    assert entity._timer is None
    assert not entity._tasks


async def test_new_sensor_remembers_latest_connection(hass, cfg):

    cfg.update(auto_update=False, api_key="OLDER_TEST_KEY")
    first = await add_entry(hass, cfg, "first")
    second_cfg = {
        **cfg,
        "name": "Second",
        "api_url": "http://another:8000/v1/systemone",
        "api_key": "SECOND_TEST_KEY",
        "model": "different-model",
    }
    second = await add_entry(hass, second_cfg, "second")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    defaults = result["data_schema"]({})
    assert defaults["api_url"] == second_cfg["api_url"]
    assert defaults["api_key"] == "SECOND_TEST_KEY"
    assert defaults["model"] == "different-model"
    assert defaults["name"] == "Decision"
    hass.config_entries.flow.async_abort(result["flow_id"])
    # Options updates are remembered, not just the original setup credentials.
    hass.config_entries.async_update_entry(
        first,
        options={"api_key": "UPDATED_TEST_KEY", "api_url": "http://updated:8000/v1/systemone"},
    )
    await hass.async_block_till_done()
    assert first.modified_at >= second.modified_at
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    defaults = result["data_schema"]({})
    assert defaults["api_url"] == "http://updated:8000/v1/systemone"
    assert defaults["api_key"] == "UPDATED_TEST_KEY"
    assert "references" not in defaults and "questions" not in defaults
    # Users can explicitly clear a remembered credential.
    defaults.update(name="Third", api_key="")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], defaults)
    assert result["step_id"] == "question_type"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "noul"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "question_key": "new_question",
            "instructions": "Is attention needed?",
            "true_description": "Attention needed",
            "false_description": "No attention needed",
        },
    )
    behavior = result["data_schema"]({})
    assert behavior["references"] == []
    behavior["auto_update"] = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], behavior)
    assert result["type"] == "create_entry"
    assert result["result"].data["api_key"] == ""
    assert result["result"].data["references"] == []
    assert list(result["result"].data["questions"]) == ["new_question"]
    await hass.async_block_till_done()
