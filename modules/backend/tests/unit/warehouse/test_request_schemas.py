"""Every string a warehouse request can carry is listed, bounded and patterned.

The shape of the request schemas is the contract, not the names of their
fields: a field called ``sql`` and a field called ``expression`` are the same
risk.  So this walks the JSON schema of every model in every
``modules/backend/app/schemas/warehouse*.py`` file and pins the exact set of
string-typed positions, each with its maximum length and pattern.  Adding any
free-text field -- whatever it is called -- fails here until it is listed with
its bounds, and a string without a maximum length or a pattern cannot be
listed at all.
"""

from __future__ import annotations

import importlib
import inspect
import uuid
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from modules.backend.app.schemas import warehouse_sources as ws

pytestmark = pytest.mark.unit

SCHEMA_DIR = Path(ws.__file__).parent

NAME = ("text", 200, ws.NAME_PATTERN)
IDENT = ("text", 1024, ws.IDENTIFIER_PATTERN)
TABLE = ("text", 2080, ws.TABLE_PATTERN)
LITERAL = ("text", 256, ws.LITERAL_PATTERN)
UUID = ("format", "uuid")
OPERATOR = ("enum", ("eq", "in", "is_not_null", "is_null", "ne", "not_in"))
METRIC_TYPE = ("enum", ("mean", "proportion"))

_FILTER = {
    "filters[].column": {IDENT},
    "filters[].operator": {OPERATOR},
    "filters[].value": {LITERAL},
    "filters[].value[]": {LITERAL},
}
_ASSIGNMENT = {
    "name": {NAME},
    "table": {TABLE},
    "columns.unit_id": {IDENT},
    "columns.experiment_key": {IDENT},
    "columns.variant": {IDENT},
    "columns.exposed_at": {IDENT},
    "kind": {("enum", ("assignment",))},
    **_FILTER,
}
_METRIC = {
    "name": {NAME},
    "table": {TABLE},
    "columns.unit_id": {IDENT},
    "columns.event_at": {IDENT},
    "columns.value": {IDENT},
    "metric_type": {METRIC_TYPE},
    "kind": {("enum", ("metric",))},
    **_FILTER,
}


def _without(d: dict, *keys: str) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


def _prefixed(prefix: str, d: dict) -> dict:
    return {f"{prefix}.{k}": v for k, v in d.items()}


#: (model, position) -> the set of string shapes allowed there.
ALLOWLIST = {
    **_prefixed("AssignmentSourceCreate", {**_ASSIGNMENT, "connection_id": {UUID}}),
    **_prefixed("AssignmentSourceUpdate", _ASSIGNMENT),
    **_prefixed("_AssignmentSourceBody", _without(_ASSIGNMENT, "kind")),
    **_prefixed("MetricSourceCreate", {**_METRIC, "connection_id": {UUID}}),
    **_prefixed("MetricSourceUpdate", _METRIC),
    **_prefixed("_MetricSourceBody", _without(_METRIC, "kind")),
    **_prefixed(
        "SourceFilterIn", {k.removeprefix("filters[]."): v for k, v in _FILTER.items()}
    ),
    **_prefixed(
        "AssignmentColumns",
        {
            k.removeprefix("columns."): v
            for k, v in _ASSIGNMENT.items()
            if k.startswith("columns.")
        },
    ),
    **_prefixed(
        "MetricColumns",
        {
            k.removeprefix("columns."): v
            for k, v in _METRIC.items()
            if k.startswith("columns.")
        },
    ),
}


def warehouse_request_models() -> list[type[BaseModel]]:
    models = []
    for path in sorted(SCHEMA_DIR.glob("warehouse*.py")):
        module = importlib.import_module(f"modules.backend.app.schemas.{path.stem}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseModel) and obj.__module__ == module.__name__:
                models.append(obj)
    return models


def _string_positions(model: type[BaseModel]) -> dict[str, set]:
    schema = model.model_json_schema(mode="validation")
    defs = schema.get("$defs", {})
    found: dict[str, set] = {}

    def walk(node: dict, path: str) -> None:
        if "$ref" in node:
            node = defs[node["$ref"].split("/")[-1]]
        for key in ("anyOf", "oneOf", "allOf"):
            for option in node.get(key, []):
                walk(option, path)
        if node.get("type") == "object" or "properties" in node:
            for name, prop in node.get("properties", {}).items():
                walk(prop, f"{path}.{name}" if path else name)
        if node.get("type") == "array":
            walk(node.get("items", {}), f"{path}[]")
        if node.get("type") == "string":
            if "enum" in node or "const" in node:
                values = node.get("enum") or [node["const"]]
                shape = ("enum", tuple(sorted(values)))
            elif node.get("format") in ("uuid",):
                shape = ("format", node["format"])
            else:
                shape = ("text", node.get("maxLength"), node.get("pattern"))
            found.setdefault(path, set()).add(shape)

    walk(schema, "")
    return found


def _all_positions() -> dict[str, set]:
    positions = {}
    for model in warehouse_request_models():
        for path, shapes in _string_positions(model).items():
            positions[f"{model.__name__}.{path}"] = shapes
    return positions


def test_the_request_models_are_found():
    names = {m.__name__ for m in warehouse_request_models()}
    assert {"AssignmentSourceCreate", "MetricSourceCreate", "SourceFilterIn"} <= names


def test_every_string_field_is_bounded_and_patterned():
    unbounded = [
        (path, shape)
        for path, shapes in _all_positions().items()
        for shape in shapes
        if shape[0] == "text" and (shape[1] is None or shape[2] is None)
    ]
    assert unbounded == []


def test_every_string_field_is_allowlisted_exactly():
    assert _all_positions() == ALLOWLIST


def test_every_request_model_forbids_unknown_fields():
    for model in warehouse_request_models():
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_no_request_model_accepts_a_float_that_is_not_bounded():
    for model in warehouse_request_models():
        schema = model.model_json_schema(mode="validation")
        for name, prop in schema.get("properties", {}).items():
            options = prop.get("anyOf", [prop])
            for option in options:
                if option.get("type") == "number":
                    assert "maximum" in option and (
                        "exclusiveMinimum" in option or "minimum" in option
                    ), (model.__name__, name)


def _metric(**overrides):
    body = {
        "connection_id": str(uuid.uuid4()),
        "kind": "metric",
        "name": "Revenue",
        "table": "acme-prod.analytics.orders",
        "columns": {"unit_id": "user_id", "event_at": "event_at", "value": "amount"},
        "metric_type": "mean",
        "cap_value": 500,
        "filters": [{"column": "status", "operator": "eq", "value": "paid"}],
    }
    body.update(overrides)
    return body


def test_valid_bodies_are_accepted():
    ws.MetricSourceCreate.model_validate(_metric())
    ws.AssignmentSourceCreate.model_validate(
        {
            "connection_id": str(uuid.uuid4()),
            "kind": "assignment",
            "name": "Exposures",
            "table": "ANALYTICS.PUBLIC.EXPOSURES",
            "columns": {
                "unit_id": "USER_ID",
                "experiment_key": "EXPERIMENT_KEY",
                "variant": "VARIANT",
                "exposed_at": "EXPOSED_AT",
            },
            "filters": [
                {"column": "PLATFORM", "operator": "in", "value": ["web", "ios"]}
            ],
        }
    )


@pytest.mark.parametrize(
    "tamper",
    ['"', "`", "'", ";", "--", "/*", " ", "\x00", "\n", "\r", " "],
)
def test_schema_tampers_refused(tamper):
    for body in (
        _metric(table="acme-prod.analytics.orders" + tamper),
        _metric(columns={"unit_id": "user_id" + tamper, "event_at": "e", "value": "v"}),
        _metric(
            filters=[{"column": "status" + tamper, "operator": "eq", "value": "paid"}]
        ),
    ):
        with pytest.raises(ValidationError):
            ws.MetricSourceCreate.model_validate(body)
    if tamper not in (" ", "--"):
        with pytest.raises(ValidationError):
            ws.MetricSourceCreate.model_validate(
                _metric(
                    filters=[
                        {"column": "status", "operator": "eq", "value": "paid" + tamper}
                    ]
                )
            )


@pytest.mark.parametrize(
    "body",
    [
        _metric(expression="1=1"),
        _metric(sql="SELECT 1"),
        _metric(table="a.b.c.d"),
        _metric(table="orders"),
        _metric(name=""),
        _metric(name="x" * 201),
        _metric(name="line\nbreak"),
        _metric(metric_type="ratio"),
        _metric(metric_type="proportion"),  # value column given
        _metric(cap_value=0),
        _metric(cap_value=float("inf")),
        _metric(cap_value=2e15),
        _metric(conversion_window_hours=0),
        _metric(conversion_window_hours="24"),
        _metric(filters=[{"column": "s", "operator": "eq", "value": "x"}] * 6),
        _metric(
            filters=[
                {"column": "s", "operator": "in", "value": [str(i) for i in range(51)]}
            ]
        ),
        _metric(filters=[{"column": "s", "operator": "in", "value": ["a", 1]}]),
        _metric(filters=[{"column": "s", "operator": "in", "value": "a"}]),
        _metric(filters=[{"column": "s", "operator": "eq", "value": ["a"]}]),
        _metric(filters=[{"column": "s", "operator": "is_null", "value": "a"}]),
        _metric(filters=[{"column": "s", "operator": "like", "value": "a%"}]),
        _metric(filters=[{"column": "s", "operator": "eq", "value": 1.5}]),
        _metric(filters=[{"column": "s", "operator": "eq", "value": "1", "extra": 1}]),
    ],
)
def test_bodies_outside_the_contract_are_refused(body):
    with pytest.raises(ValidationError):
        ws.MetricSourceCreate.model_validate(body)
