"""Human-friendly forms translated to the typed model question contract."""

from .model import InvalidConfig


def build_question(kind: str, fields: dict) -> dict:
    """Build Choice, Score, or Noul without requiring users to write JSON."""
    name = fields.get("question_key", "decision").strip()
    if not name:
        raise InvalidConfig("question_key", "invalid_name")
    instructions = fields.get("instructions", "").strip()
    if not instructions:
        raise InvalidConfig("instructions", "invalid_instructions")
    question = {"type": kind, "instructions": instructions}
    if kind == "choice":
        criteria = {}
        for line in fields.get("criteria", "").splitlines():
            if not line.strip():
                continue
            key, separator, description = line.partition(":")
            key = key.strip()
            description = description.strip() if separator else key
            if not key or not description or key in criteria:
                raise InvalidConfig("criteria", "invalid_choices")
            criteria[key] = description
        if not 2 <= len(criteria) <= 255:
            raise InvalidConfig("criteria", "invalid_choices")
        question["criteria"] = criteria
    elif kind == "score":
        criteria = [
            line.strip() for line in fields.get("criteria", "").splitlines() if line.strip()
        ]
        if not 2 <= len(criteria) <= 10 or len(set(criteria)) != len(criteria):
            raise InvalidConfig("criteria", "invalid_score")
        question["criteria"] = criteria
    elif kind == "noul":
        question["criteria"] = {
            "true": fields.get("true_description", "The statement is true").strip(),
            "false": fields.get("false_description", "The statement is false").strip(),
        }
        if not all(question["criteria"].values()):
            raise InvalidConfig("instructions", "invalid_instructions")
    else:
        raise ValueError("Unsupported guided question type")
    return {name: question}


def builder_defaults(kind: str, questions: dict) -> dict:
    """Allow round-trip editing of a single guided question."""
    if len(questions) != 1:
        return {}
    name, question = next(iter(questions.items()))
    if question.get("type") != kind:
        return {}
    result = {"question_key": name, "instructions": question.get("instructions", "")}
    criteria = question.get("criteria")
    if kind == "choice" and isinstance(criteria, dict):
        result["criteria"] = "\n".join(
            f"{key}: {description}" for key, description in criteria.items()
        )
    elif kind == "score" and isinstance(criteria, list):
        result["criteria"] = "\n".join(str(item) for item in criteria)
    elif kind == "noul" and isinstance(criteria, dict):
        result.update(
            true_description=criteria.get("true", ""), false_description=criteria.get("false", "")
        )
    return result
