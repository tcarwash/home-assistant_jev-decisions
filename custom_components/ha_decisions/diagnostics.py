"""Redacted diagnostics: omit prompts, model output, states, and credentials."""

from .const import CONF_AUTO_UPDATE, CONF_BACKEND, CONF_DEBOUNCE, CONF_SCAN_INTERVAL, CONF_TIMEOUT
from .model import effective_config


async def async_get_config_entry_diagnostics(hass, entry):
    cfg = effective_config(entry.data, entry.options)
    return {
        "version": "0.2.0",
        "settings": {
            key: cfg[key]
            for key in (
                CONF_BACKEND,
                CONF_AUTO_UPDATE,
                CONF_DEBOUNCE,
                CONF_SCAN_INTERVAL,
                CONF_TIMEOUT,
            )
        },
        "question_count": len(cfg["questions"]),
        "reference_count": len(cfg["references"]),
        "sensors": [
            {
                "status": entity.extra_state_attributes.get("status"),
                "error_type": entity.extra_state_attributes.get("error_type"),
                "http_status": entity.extra_state_attributes.get("http_status"),
            }
            for entity in hass.data.get("ha_decisions", {}).get("entities", {}).values()
            if entity.entry.entry_id == entry.entry_id
        ],
    }
