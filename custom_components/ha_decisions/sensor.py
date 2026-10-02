"""Event-driven decision sensor with coalesced, serialized requests."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .api import DecisionError, async_request
from .const import (
    CONF_AUTO_UPDATE,
    CONF_BACKEND,
    CONF_DEBOUNCE,
    CONF_MODEL,
    CONF_PRIMARY_QUESTION,
    CONF_REFERENCES,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from .model import answer_state_value, effective_config, parse_questions

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DecisionEntity(hass, entry)])


class DecisionEntity(SensorEntity):
    """Expose compact state, structured answers, and refresh status."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:thought-bubble-outline"

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.cfg = effective_config(entry.data, entry.options)
        self.cfg["questions"] = parse_questions(self.cfg["questions"])
        self._attr_name = self.cfg.get("name", entry.title)
        self._attr_unique_id = entry.entry_id
        self._attr_native_value = "waiting"
        self._attr_extra_state_attributes = {"status": "waiting", "answers": {}, "error": None}
        self._lock = asyncio.Lock()
        self._timer = None
        self._tasks = set()
        self._removed = False
        self._generation = 0
        self._started = False

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.hass.data[DOMAIN]["entities"][self.entity_id] = self
        references = [ref for ref in self.cfg[CONF_REFERENCES] if ref != self.entity_id]
        if self.cfg[CONF_AUTO_UPDATE]:
            if references:
                self.async_on_remove(
                    async_track_state_change_event(
                        self.hass,
                        references,
                        self._on_change,
                    )
                )
            # Wait for startup so other integrations have populated their states.
            self.async_on_remove(async_at_started(self.hass, self._on_start))
            if self.cfg[CONF_SCAN_INTERVAL]:
                self.async_on_remove(
                    async_track_time_interval(
                        self.hass,
                        self._on_interval,
                        timedelta(seconds=self.cfg[CONF_SCAN_INTERVAL]),
                    )
                )

    @callback
    def _on_start(self, hass):
        self._started = True
        self._schedule(1)

    @callback
    def _on_interval(self, now):
        if self._started:
            self._schedule(0)

    @callback
    def _on_change(self, event):
        if event.data.get("old_state") == event.data.get("new_state"):
            return
        self._generation += 1
        if self._started:
            self._schedule(self.cfg[CONF_DEBOUNCE])

    @callback
    def _schedule(self, delay):
        if self._removed:
            return
        if self._timer is not None:
            self._timer.cancel()
        # Cancel only the pending timer, never the active HTTP request.
        self._timer = asyncio.get_running_loop().call_later(delay, self._launch)

    @callback
    def _launch(self):
        self._timer = None
        if self._removed or self._lock.locked():
            return  # Input changes during a request are handled by its generation check.
        task = self.entry.async_create_background_task(
            self.hass,
            self.async_ask(),
            "refresh decision sensor",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def async_will_remove_from_hass(self):
        self._removed = True
        if self._timer:
            self._timer.cancel()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
        self.hass.data.get(DOMAIN, {}).get("entities", {}).pop(self.entity_id, None)
        await super().async_will_remove_from_hass()

    async def async_ask(self):
        async with self._lock:
            if self._removed:
                return
            # A manual request supersedes a pending automatic refresh.
            if self._timer:
                self._timer.cancel()
                self._timer = None
            generation = self._generation
            self._attr_extra_state_attributes = {
                **self._attr_extra_state_attributes,
                "status": "asking",
                "last_attempted": dt_util.utcnow().isoformat(),
                "error": None,
                "error_type": None,
                "http_status": None,
            }
            # Retain the last decision during refresh, rather than triggering automations with "asking".
            self.async_write_ha_state()
            try:
                state = {}
                for ref in self.cfg[CONF_REFERENCES]:
                    if ref == self.entity_id:
                        continue
                    entity = self.hass.states.get(ref)
                    state[ref] = (
                        None
                        if entity is None
                        else {
                            "state": entity.state,
                            "attributes": dict(entity.attributes),
                            "last_changed": entity.last_changed.isoformat(),
                        }
                    )
                answers = await async_request(async_get_clientsession(self.hass), self.cfg, state)
                if self._removed:
                    return
                self._attr_native_value = answer_state_value(
                    answers, self.cfg[CONF_PRIMARY_QUESTION]
                )
                primary = self.cfg[CONF_PRIMARY_QUESTION]
                answer = (
                    answers.get(primary)
                    if primary
                    else next(iter(answers.values()))
                    if len(answers) == 1
                    else None
                )
                # Whitelist metadata so model-supplied keys cannot overwrite integration status.
                metadata = {
                    key: answer[key]
                    for key in (
                        "type",
                        "choice",
                        "score",
                        "noul",
                        "confidence",
                        "answer_confidence",
                        "probabilities",
                        "legend",
                        "action",
                    )
                    if isinstance(answer, dict) and key in answer
                }
                self._attr_extra_state_attributes = {
                    **metadata,
                    "answers": answers,
                    "response": answers,
                    "backend": self.cfg[CONF_BACKEND],
                    "model": self.cfg[CONF_MODEL],
                    "referenced_entities": list(state),
                    "asked_at": dt_util.utcnow().isoformat(),
                    "status": "complete",
                    "error": None,
                }
            except DecisionError as err:
                _LOGGER.warning("Decision request failed for %s: %s", self.entity_id, err)
                self._attr_native_value = "error"
                self._attr_extra_state_attributes.update(
                    status="error",
                    error=str(err),
                    error_type=err.code,
                    http_status=err.http_status,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Do not log backend exception details; these may include URLs or credentials.
                _LOGGER.error("Unexpected decision request failure for %s", self.entity_id)
                self._attr_native_value = "error"
                self._attr_extra_state_attributes.update(
                    status="error", error="Unexpected request failure", error_type="internal_error"
                )
            if not self._removed:
                self.async_write_ha_state()
                if generation != self._generation:
                    self._schedule(self.cfg[CONF_DEBOUNCE])
