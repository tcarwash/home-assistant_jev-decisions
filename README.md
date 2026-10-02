# HA Decisions

Turn selected Home Assistant entity states into structured decisions using a local or remote model. Each instance creates one sensor, configured entirely through the UI.

Use it for questions such as “Should the battery charge?”, “Does this room need attention?”, or “How urgent is this alert?” Home Assistant automations can act on the resulting sensor state. The integration itself never calls device actions or executes model-generated commands.

## Install

Requires Home Assistant **2025.12 or newer** and a separately running compatible model endpoint. No model weights or GPU runtime are installed inside Home Assistant.

### Manual installation

1. Copy `custom_components/ha_decisions` into your Home Assistant configuration directory, producing `/config/custom_components/ha_decisions/manifest.json`.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → HA Decisions**.

The release ZIP includes the `custom_components` directory; extract it into your Home Assistant configuration directory. Do not copy the entire repository into `custom_components`.

### HACS custom repository

Once this project is published on GitHub, add its actual repository URL in **HACS → Custom repositories**, category **Integration**, install HA Decisions, then restart Home Assistant. The repository has the layout and `hacs.json` for this route. It is not currently submitted to the HACS default catalog.

## Build a sensor without JSON

1. **Connection:** name the sensor, select the backend protocol, and enter the complete endpoint URL, model identifier, and optional bearer API key.
2. **Question:** choose **Choice**, **Noul**, or **Score** and write the question or statement.
3. **Inputs:** select the entity states the question needs. Set automatic evaluation, debounce, optional periodic refresh, and timeout.

The URL, API key, backend, and model are saved across Home Assistant restarts. When you add another sensor, the connection form prefills the most recently configured sensor’s connection, including a masked API key. You can change these defaults or clear the API key. Questions and input entities are not copied. Each new sensor stores its own connection settings; editing one does not update the others.

Add the integration again to create another sensor. Each sensor can use its own endpoint, question, and input entities. Use the integration’s **Configure** menu to edit the connection, question, or refresh behavior independently.

### Choice

Enter options one per line using `label: description`:

```text
charge: Battery is low and available power makes charging appropriate
idle: Battery has enough charge or charging is inappropriate
unknown: Required information is unavailable
```

The sensor state is the selected label, such as `charge`. The builder accepts 2–255 unique labels. A line without a colon uses that text as both label and description.

### Noul

Write a statement, for example “The battery needs charging”, and descriptions of what true and false mean. The builder generates `type: noul` with `true`/`false` criteria.

The sensor state is the **probability that the statement is true**, from **0 to 1**. A state of `0.85` means 85%. Use a numeric threshold in automations; a Noul sensor is not an on/off binary sensor.

### Score

Write what should be rated, then enter 2–10 distinct descriptions, one per line, in ascending order:

```text
No action needed
Needs attention soon
Immediate action needed
```

The builder sends an ordered criteria list. Levels start at **0**, so this example yields an expected score from **0 to 2**, potentially fractional, such as `1.73`. The sensor preserves the numeric result, distribution, and legend when returned by the server.

### Advanced questions

Choose **Advanced** to enter a named JSON question map, including multiple questions, custom types, and any backend-specific fields. JSON fences and wrapped `{"questions": {...}}` maps are also accepted. See [examples/questions.json](examples/questions.json).

For multiple questions, set a **primary question identifier** to use that answer as the sensor state. Leaving it blank produces `completed`, with all results in the `answers` attribute. Selecting a guided type intentionally replaces the map with one question; use advanced editing to retain a multi-question configuration.

## Backend protocols

### Typed JSON (Laya / Jev compatible)

Enter the full endpoint URL, for example `http://model-server:8000/v1/systemone`. The default model identifier is `typed-decisions`; change it to one your server accepts.

The integration sends a JSON POST:

```json
{
  "model": "typed-decisions",
  "state": {
    "sensor.battery": {
      "state": "20",
      "attributes": {"unit_of_measurement": "%"},
      "last_changed": "2026-10-01T12:00:00+00:00"
    }
  },
  "questions": {
    "needs_charge": {
      "type": "noul",
      "instructions": "The battery needs charging.",
      "criteria": {"true": "Battery is low", "false": "Battery has sufficient charge"}
    }
  }
}
```

Expected response:

```json
{"answers": {"needs_charge": {"type": "noul", "noul": 0.85, "confidence": 0.7}}}
```

Typed results use `choice` for a label, `score` for an expected ordinal level, or `noul` for probability true. Incomplete answers, unknown choice labels, nonfinite numeric answers, and out-of-range Noul probabilities produce an error. Other question types pass through and use scalar fields such as `value` or `text` for the sensor state.

For the underlying model contract, see the [Laya documentation](https://github.com/NandhaKishorM/laya#readme). A provider being HTTP-compatible does not establish its model accuracy or probability calibration.

### OpenAI-compatible chat completions

Enter the full chat endpoint, for example `http://model-server:8080/v1/chat/completions`, and a model identifier supported by that server. This uses a `messages` request and asks the model to generate the same named `answers` JSON contract. It supports servers that implement chat completions and whose models can follow the JSON instructions. No OpenAI account is required for a local server.

The integration parses the returned `choices[0].message.content`, including fenced JSON, and applies the same answer validation. Generated probabilities are model estimates; they do not inherit the calibration of a typed decision model.

URLs are used exactly as supplied. No endpoint suffix is appended. Bearer authentication is optional. Redirects are rejected; enter the final URL directly.

## Updates and automation

Automatic evaluation runs after Home Assistant starts, on selected entity changes (including attribute changes), and optionally at a configured interval. A 2-second debounce is the default; periodic refresh is disabled by default. Input changes during an active request trigger one follow-up request using the latest states. Refresh requests are serialized per sensor.

Disable automatic evaluation to use manual-only operation. Refresh explicitly through **Developer tools → Actions → HA Decisions: Refresh decision**:

```yaml
action: ha_decisions.ask
data:
  entity_id: sensor.battery_decision
```

`entity_id` also accepts a list. Omit it to refresh all loaded decision sensors. An invalid or empty explicit selection raises an error.

During refresh the previous sensor state is retained and `status` becomes `asking`. A successful result sets `status: complete`. Failure sets the state and status to `error`; old answers may remain in attributes for troubleshooting, so gate automations on `status == 'complete'`.

Attributes include `answers`, the backward-compatible `response` alias, backend/model, last successful timestamp, and returned metadata such as confidence and probabilities. Input snapshots and prompts are not duplicated into sensor attributes. Model response bodies and endpoint credentials are omitted from logs and downloaded diagnostics.

See [examples/automations.yaml](examples/automations.yaml) for choice, Noul, and score triggers. Automations evaluate model output, so choose thresholds and validate decisions against your own household data before connecting them to devices.

## Privacy and errors

Only selected entities are sent, but **all attributes of those selected entities** are included. Select inputs deliberately, especially when using a remote server. Missing entities are sent as `null`; unavailable states remain explicit. API keys are stored in Home Assistant config entries and displayed using a password field; use normal HA backup/access protections.

On error, inspect `error`, `error_type`, and `http_status` on the sensor. Common causes are an unreachable server, wrong full endpoint path, unsupported model identifier, authentication failure, or invalid response JSON. The request timeout is configurable from 1 to 300 seconds. Responses are limited to 1 MiB.

## Upgrade from the original Jev/Laya integration

Replace the old `ha_decisions` directory with `custom_components/ha_decisions` from this repository and restart Home Assistant. The domain and config-entry-based sensor unique IDs are unchanged. Existing endpoint URLs, named question maps, and old free-text questions are retained. Legacy `agent: laya` maps to model `typed-decisions`; `agent: jev` maps to `jev`. Open Configure to adopt the new builder and connection settings.

## Development and redistribution

Licensed under [MIT](LICENSE). Build a manual-install release with:

```bash
python scripts/build_release.py
```

The ZIP is written to `dist/ha_decisions-0.2.0.zip` and excludes environments, caches, tests, and local credentials. It contains the integration, documentation, examples, license, and changelog.

Before publishing to your own GitHub repository, set the real documentation URL, issue tracker, and maintainer:

```bash
python scripts/prepare_repository.py YOUR_OWNER/YOUR_REPOSITORY --maintainer YOUR_GITHUB_USERNAME
```

Until then, manifest documentation points to the upstream backend contract. The workflow checks code and tests against a minimum and a newer Home Assistant release and builds an installable ZIP. HACS requires real publication metadata and a published repository; this package is not a claim of HACS catalog acceptance.

Run development checks with Python 3.13:

```bash
uv venv --python 3.13
uv pip install -r requirements-dev.txt
.venv/bin/ruff check custom_components tests scripts
.venv/bin/ruff format --check custom_components tests scripts
.venv/bin/pytest -q
python scripts/build_release.py
```

Tests use real Home Assistant config/option flows, entity setup, action registration and unload, plus a local HTTP server for transport. They do not connect to a production Home Assistant instance or a real model service.
