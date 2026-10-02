"""Shared integration constants."""

from homeassistant.const import Platform

DOMAIN = "ha_decisions"
PLATFORMS = [Platform.SENSOR]
SERVICE_ASK = "ask"
CONF_AGENT = "agent"  # Legacy configuration only.
CONF_API_URL = "api_url"
CONF_API_KEY = "api_key"
CONF_QUESTION = "question"  # Legacy configuration only.
CONF_QUESTIONS = "questions"
CONF_REFERENCES = "references"
CONF_BACKEND = "backend"
CONF_MODEL = "model"
CONF_PRIMARY_QUESTION = "primary_question"
CONF_TIMEOUT = "timeout"
CONF_DEBOUNCE = "debounce"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_AUTO_UPDATE = "auto_update"
BACKEND_TYPED = "typed_json"
BACKEND_OPENAI = "openai_compatible"
DEFAULTS = {
    CONF_BACKEND: BACKEND_TYPED,
    CONF_MODEL: "typed-decisions",
    CONF_API_KEY: "",
    CONF_REFERENCES: [],
    CONF_PRIMARY_QUESTION: "",
    CONF_TIMEOUT: 60,
    CONF_DEBOUNCE: 2,
    CONF_SCAN_INTERVAL: 0,
    CONF_AUTO_UPDATE: True,
}
DEFAULT_QUESTIONS = {
    "decision": {
        "type": "choice",
        "instructions": "Decide whether action is needed from the supplied entity states. Choose unknown when information is missing.",
        "criteria": {
            "yes": "Action is needed",
            "no": "No action needed",
            "unknown": "Insufficient information",
        },
    }
}
