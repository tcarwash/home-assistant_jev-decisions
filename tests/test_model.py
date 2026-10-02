import json

import pytest

from custom_components.ha_decisions.builder import build_question, builder_defaults
from custom_components.ha_decisions.model import (
    InvalidConfig,
    answer_state_value,
    build_payload,
    effective_config,
    extract_answers,
    parse_questions,
    validate_config,
)


@pytest.mark.parametrize(
    "kind,fields,criteria",
    [
        (
            "choice",
            {"criteria": "charge: Needs charging\nidle: Enough charge"},
            {"charge": "Needs charging", "idle": "Enough charge"},
        ),
        (
            "score",
            {"criteria": "Safe\nNeeds attention\nCritical"},
            ["Safe", "Needs attention", "Critical"],
        ),
        (
            "noul",
            {"true_description": "Charging needed", "false_description": "Enough charge"},
            {"true": "Charging needed", "false": "Enough charge"},
        ),
    ],
)
def test_guided_roundtrip(kind, fields, criteria):
    fields = {
        "question_key": "battery",
        "instructions": "Does the battery need attention?",
        **fields,
    }
    questions = build_question(kind, fields)
    assert questions["battery"]["criteria"] == criteria
    assert build_question(kind, builder_defaults(kind, questions)) == questions


@pytest.mark.parametrize(
    "kind,criteria",
    [("choice", "yes"), ("choice", "yes: a\nyes: b"), ("score", "one"), ("score", "one\none")],
)
def test_bad_builder_options(kind, criteria):
    with pytest.raises(InvalidConfig):
        build_question(
            kind, {"question_key": "q", "instructions": "Question", "criteria": criteria}
        )


@pytest.mark.parametrize(
    "raw",
    [
        '{"q": {"type": "custom", "extra": [1]}}',
        '```json\n{"q":{"type":"custom","extra":[1]}}\n```',
    ],
)
def test_preserve_custom_fields(raw):
    assert parse_questions(raw) == {"q": {"type": "custom", "extra": [1]}}


@pytest.mark.parametrize("raw", ["[]", "{}", '{"q":1}', '{"q":{}}', '{"q":{"type":12}}'])
def test_reject_bad_questions(raw):
    with pytest.raises(ValueError):
        parse_questions(raw)


def test_legacy_config():
    cfg = effective_config(
        {
            "agent": "jev",
            "api_url": "http://original:8000/v1/systemone",
            "question": "Original prompt",
        }
    )
    assert cfg["model"] == "jev"
    assert cfg["api_url"] == "http://original:8000/v1/systemone"
    assert cfg["questions"]["decision"]["instructions"] == "Original prompt"
    assert effective_config({"agent": "laya"})["model"] == "typed-decisions"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://host/x",
        "http://",
        "http://user:secret@host",
        "http://host:99999",
        "https://host/path#secret",
    ],
)
def test_url_validation(cfg, url):
    with pytest.raises(InvalidConfig) as err:
        validate_config({**cfg, "api_url": url})
    assert err.value.field == "api_url"


@pytest.mark.parametrize("kind,value", [("choice", "yes"), ("score", 1.73), ("noul", 0.89)])
def test_numeric_and_choice_states(cfg, kind, value):
    cfg["questions"] = {"decision": {"type": kind}}
    answers = extract_answers({"answers": {"decision": {kind: value}}}, cfg)
    assert answers["decision"]["type"] == kind
    assert answer_state_value(answers) == value


@pytest.mark.parametrize(
    "kind,value", [("noul", 1.2), ("score", float("nan")), ("score", True), ("choice", 1)]
)
def test_reject_invalid_typed_answers(cfg, kind, value):
    cfg["questions"] = {"decision": {"type": kind}}
    with pytest.raises(ValueError):
        extract_answers({"answers": {"decision": {kind: value}}}, cfg)


def test_missing_answers_and_primary(cfg):
    cfg["questions"] = {"q1": {"type": "noul"}, "q2": {"type": "score"}}
    with pytest.raises(ValueError):
        extract_answers({"answers": {"q1": {"noul": 0.8}}}, cfg)
    answers = {"q1": {"noul": 0.8}, "q2": {"score": 1.8}}
    assert answer_state_value(answers) == "completed"
    assert answer_state_value(answers, "q2") == 1.8


def test_openai_payload_and_parsing(cfg):
    cfg["backend"] = "openai_compatible"
    payload = build_payload(cfg, {"sensor.battery": {"state": "20"}})
    assert payload["model"] == cfg["model"]
    assert json.loads(payload["messages"][1]["content"])["questions"] == cfg["questions"]
    answers = {"decision": {"choice": "yes"}}
    result = {
        "choices": [
            {"message": {"content": "```json\n" + json.dumps({"answers": answers}) + "\n```"}}
        ]
    }
    assert extract_answers(result, cfg)["decision"]["choice"] == "yes"
