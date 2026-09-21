"""Validate requests against the shared OpenAPI 3.1 contract, not permissive dicts."""

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jsonschema
import yaml

from .errors import PharmaError, require


@lru_cache
def specification():
    data = yaml.safe_load((Path(__file__).parent / "resources/openapi.yaml").read_text(encoding="utf-8"))
    data["paths"] = {("/api/pharma" + key if key in ("/healthz", "/readyz") else key.replace("/api/v1", "/api/pharma/v1")): value for key, value in data["paths"].items()}
    data["servers"] = [{"url": "/", "description": "Same-origin PharmaScope deployment"}]
    data["info"]["description"] = "Implemented PharmaScope API. All business resources are workspace scoped and authenticated; report evidence is validated server-side."
    return data


def validate(name, value):
    root = specification()
    schema = {"$ref": f"#/components/schemas/{name}", "components": root["components"]}
    try:
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(value)
    except jsonschema.ValidationError as exc:
        raise PharmaError("VALIDATION_ERROR", "请求字段不符合接口规范", 422, {"field": ".".join(map(str, exc.absolute_path)), "reason": exc.message[:400]}) from None
    if name.endswith("Patch") or name == "MemberUpdate":
        require(bool(value), "VALIDATION_ERROR", "至少提供一个需要修改的字段", 422)
    if name == "Schedule":
        validate_schedule(value)
    if "schedule" in value:
        validate_schedule(value["schedule"])
    if name == "ResearchInput":
        window = value["time_range"]
        try:
            ZoneInfo(window["timezone"])
            require(datetime.fromisoformat(window["start"].replace("Z", "+00:00")) < datetime.fromisoformat(window["end_exclusive"].replace("Z", "+00:00")), "VALIDATION_ERROR", "结束时间必须晚于开始时间", 422)
        except (ValueError, ZoneInfoNotFoundError):
            raise PharmaError("VALIDATION_ERROR", "无效的日期或时区", 422) from None
    return value


def validate_schedule(value):
    try:
        ZoneInfo(value["timezone"])
        hour, minute = map(int, value["local_time"].split(":"))
        assert 0 <= hour < 24 and 0 <= minute < 60
        assert value["frequency"] != "weekly" or value["weekday"] in range(1, 8)
    except (KeyError, ValueError, AssertionError, ZoneInfoNotFoundError):
        raise PharmaError("VALIDATION_ERROR", "无效的排程时间或时区", 422) from None
