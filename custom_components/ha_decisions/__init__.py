"""Configurable decision sensors for Home Assistant."""

from __future__ import annotations

import asyncio

import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS, SERVICE_ASK


async def async_setup_entry(hass, entry):
    domain_data = hass.data.setdefault(DOMAIN, {"entities": {}, "entries": set()})
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    domain_data["entries"].add(entry.entry_id)

    async def ask(call):
        entities = hass.data[DOMAIN]["entities"]
        entity_ids = call.data.get("entity_id")
        if entity_ids is not None:
            if not entity_ids or any(item not in entities for item in entity_ids):
                raise ServiceValidationError("Select loaded HA Decisions sensor entities")
            targets = [entities[item] for item in entity_ids]
        else:
            targets = list(entities.values())
        await asyncio.gather(*(entity.async_ask() for entity in targets))

    if not hass.services.has_service(DOMAIN, SERVICE_ASK):
        hass.services.async_register(
            DOMAIN,
            SERVICE_ASK,
            ask,
            schema=vol.Schema({vol.Optional("entity_id"): cv.entity_ids}),
        )
    return True


async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN]["entries"].discard(entry.entry_id)
        if not hass.data[DOMAIN]["entries"]:
            hass.services.async_remove(DOMAIN, SERVICE_ASK)
    return unloaded
