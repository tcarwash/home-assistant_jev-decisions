"""Guided UI setup and editing for decision sensors."""

from __future__ import annotations

import json

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .builder import build_question, builder_defaults
from .const import (
    BACKEND_OPENAI,
    BACKEND_TYPED,
    CONF_API_KEY,
    CONF_API_URL,
    CONF_AUTO_UPDATE,
    CONF_BACKEND,
    CONF_DEBOUNCE,
    CONF_MODEL,
    CONF_PRIMARY_QUESTION,
    CONF_QUESTIONS,
    CONF_REFERENCES,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    DOMAIN,
)
from .model import InvalidConfig, effective_config, parse_questions, validate_config

MULTILINE = selector.TextSelector(selector.TextSelectorConfig(multiline=True))


def connection_schema(cfg):
    return vol.Schema(
        {
            vol.Required("name", default=cfg.get("name", "Decision")): str,
            vol.Required(CONF_BACKEND, default=cfg[CONF_BACKEND]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[BACKEND_TYPED, BACKEND_OPENAI], translation_key="backend"
                )
            ),
            vol.Required(CONF_API_URL, default=cfg.get(CONF_API_URL, "")): str,
            vol.Optional(CONF_API_KEY, default=cfg[CONF_API_KEY]): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_MODEL, default=cfg[CONF_MODEL]): str,
        }
    )


def behavior_schema(cfg):
    return vol.Schema(
        {
            vol.Optional(CONF_REFERENCES, default=cfg[CONF_REFERENCES]): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
            vol.Required(CONF_AUTO_UPDATE, default=cfg[CONF_AUTO_UPDATE]): bool,
            vol.Required(CONF_DEBOUNCE, default=cfg[CONF_DEBOUNCE]): vol.All(
                vol.Coerce(float), vol.Range(min=0, max=300)
            ),
            vol.Required(CONF_SCAN_INTERVAL, default=cfg[CONF_SCAN_INTERVAL]): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=86400)
            ),
            vol.Required(CONF_TIMEOUT, default=cfg[CONF_TIMEOUT]): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=300)
            ),
        }
    )


class BuilderSteps:
    """Shared steps used for both creation and options editing."""

    _cfg: dict
    _is_options = False

    async def async_step_question_type(self, user_input=None):
        return self.async_show_menu(
            step_id="question_type", menu_options=["choice", "noul", "score", "advanced"]
        )

    async def async_step_choice(self, user_input=None):
        return await self._guided("choice", user_input)

    async def async_step_noul(self, user_input=None):
        return await self._guided("noul", user_input)

    async def async_step_score(self, user_input=None):
        return await self._guided("score", user_input)

    async def _guided(self, kind, user_input):
        errors = {}
        if user_input is not None:
            try:
                questions = build_question(kind, user_input)
            except InvalidConfig as err:
                errors[err.field] = err.code
            else:
                self._cfg[CONF_QUESTIONS] = questions
                self._cfg[CONF_PRIMARY_QUESTION] = next(iter(questions))
                return await self._after_question()
        defaults = {**builder_defaults(kind, self._cfg[CONF_QUESTIONS]), **(user_input or {})}
        fields = {
            vol.Required("question_key", default=defaults.get("question_key", "decision")): str,
            vol.Required("instructions", default=defaults.get("instructions", "")): MULTILINE,
        }
        if kind in ("choice", "score"):
            example = (
                "yes: Action is needed\nno: No action needed\nunknown: Information is missing"
                if kind == "choice"
                else "No action needed\nAttention needed soon\nImmediate action needed"
            )
            fields[vol.Required("criteria", default=defaults.get("criteria", example))] = MULTILINE
        else:
            fields[
                vol.Required(
                    "true_description",
                    default=defaults.get("true_description", "The statement is true"),
                )
            ] = str
            fields[
                vol.Required(
                    "false_description",
                    default=defaults.get("false_description", "The statement is false"),
                )
            ] = str
        return self.async_show_form(step_id=kind, data_schema=vol.Schema(fields), errors=errors)

    async def async_step_advanced(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                candidate = validate_config({**self._cfg, **user_input})
            except InvalidConfig as err:
                errors[err.field] = err.code
            else:
                self._cfg = candidate
                return await self._after_question()
        defaults = {**self._cfg, **(user_input or {})}
        raw = defaults[CONF_QUESTIONS]
        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_QUESTIONS,
                        default=raw if isinstance(raw, str) else json.dumps(raw, indent=2),
                    ): MULTILINE,
                    vol.Optional(
                        CONF_PRIMARY_QUESTION, default=defaults[CONF_PRIMARY_QUESTION]
                    ): str,
                }
            ),
            errors=errors,
        )

    async def _after_question(self):
        return self._save() if self._is_options else await self.async_step_behavior()

    async def async_step_behavior(self, user_input=None):
        if user_input is not None:
            self._cfg.update(user_input)
            return self._save()
        return self.async_show_form(step_id="behavior", data_schema=behavior_schema(self._cfg))

    async def _connection(self, step_id, user_input):
        errors = {}
        if user_input is not None:
            try:
                data = validate_config({**self._cfg, **user_input})
            except InvalidConfig as err:
                errors[err.field] = err.code
            else:
                self._cfg = data
                if self._is_options:
                    return self._save()
                await self.async_set_unique_id(data["name"].casefold())
                self._abort_if_unique_id_configured()
                return await self.async_step_question_type()
        return self.async_show_form(
            step_id=step_id,
            data_schema=connection_schema({**self._cfg, **(user_input or {})}),
            errors=errors,
        )

    def _save(self):
        return self.async_create_entry(
            title="" if self._is_options else self._cfg["name"], data=self._cfg
        )


class DecisionsConfigFlow(BuilderSteps, config_entries.ConfigFlow, domain=DOMAIN):
    """One configuration entry per decision sensor."""

    VERSION = 1

    def __init__(self):
        self._cfg = effective_config({})
        self._connection_defaults_loaded = False

    async def async_step_user(self, user_input=None):
        if not self._connection_defaults_loaded:
            self._connection_defaults_loaded = True
            entries = self.hass.config_entries.async_entries(DOMAIN, include_ignore=False)
            if entries:
                latest = max(entries, key=lambda entry: entry.modified_at)
                remembered = effective_config(latest.data, latest.options)
                # Copy connection settings only: never another sensor's question or inputs.
                for key in (CONF_API_URL, CONF_API_KEY, CONF_BACKEND, CONF_MODEL):
                    if key in remembered:
                        self._cfg[key] = remembered[key]
        return await self._connection("user", user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return DecisionsOptionsFlow()


class DecisionsOptionsFlow(BuilderSteps, config_entries.OptionsFlow):
    """Edit connection, questions, or behavior without reentering other settings."""

    _is_options = True

    async def async_step_init(self, user_input=None):
        self._cfg = effective_config(self.config_entry.data, self.config_entry.options)
        # Normalize legacy text/fenced JSON question maps before using the builder.
        self._cfg[CONF_QUESTIONS] = parse_questions(self._cfg[CONF_QUESTIONS])
        return self.async_show_menu(
            step_id="init", menu_options=["connection", "question_type", "behavior"]
        )

    async def async_step_connection(self, user_input=None):
        return await self._connection("connection", user_input)
