"""HTTP transport with bounded reads and credential-safe errors."""

from __future__ import annotations

import json

import aiohttp

from .const import CONF_API_KEY, CONF_API_URL, CONF_TIMEOUT
from .model import build_payload, extract_answers

MAX_RESPONSE_BYTES = 1024 * 1024


class DecisionError(Exception):
    """An actionable error without endpoint credentials or response bodies."""

    def __init__(self, code: str, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


async def async_request(session: aiohttp.ClientSession, cfg: dict, state: dict) -> dict:
    """Ask once; never follow redirects with an API credential."""
    headers = {"Content-Type": "application/json"}
    if cfg.get(CONF_API_KEY):
        headers["Authorization"] = f"Bearer {cfg[CONF_API_KEY]}"
    try:
        async with session.post(
            cfg[CONF_API_URL],
            json=build_payload(cfg, state),
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=cfg[CONF_TIMEOUT]),
            allow_redirects=False,
        ) as response:
            if not 200 <= response.status < 300:
                raise DecisionError(
                    "http_error", f"Endpoint returned HTTP {response.status}", response.status
                )
            body = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise DecisionError("response_too_large", "Response exceeds 1 MiB")
            try:
                return extract_answers(json.loads(body), cfg)
            except (ValueError, TypeError, KeyError) as err:
                raise DecisionError(
                    "invalid_response", "Endpoint returned invalid or incomplete answer JSON"
                ) from err
    except TimeoutError as err:
        raise DecisionError(
            "timeout", "Endpoint did not respond before the configured timeout"
        ) from err
    except aiohttp.ClientError as err:
        raise DecisionError(
            "connection_error",
            "Cannot connect to the endpoint; check its URL, network, and TLS certificate",
        ) from err
