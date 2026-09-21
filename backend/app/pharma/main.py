"""PharmaScount API with its own authentication boundary and executable contract."""

import asyncio
import json
import logging
from datetime import timedelta
from uuid import UUID

import anyio
import jsonschema
from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from . import api, auth, reports
from .contract import specification, validate
from .db import digest, now, transaction, uid
from .errors import PharmaError, require

logger = logging.getLogger(__name__)
app = FastAPI(title="PharmaScount", docs_url="/api/pharma/docs", openapi_url="/api/pharma/openapi.json", redoc_url=None)
app.openapi = specification
IDEMPOTENT = {"runs_create", "sources_sync", "subscriptions_trigger", "reports_publish", "runs_retry"}
TERMINAL = {"completed", "partial", "failed", "cancelled", "recovery_required", "awaiting_input"}


def project(value, schema):
    if "$ref" in schema:
        schema = specification()["components"]["schemas"][schema["$ref"].split("/")[-1]]
    if value is None:
        return None
    if "anyOf" in schema:
        schema = next((s for s in schema["anyOf"] if s.get("type") != "null"), {})
        return project(value, schema)
    if isinstance(value, dict) and "properties" in schema:
        return {key: project(value[key], child) for key, child in schema["properties"].items() if key in value}
    if isinstance(value, list) and "items" in schema:
        return [project(item, schema["items"]) for item in value]
    return value


def response_schema(operation, status):
    response = operation.get("responses", {}).get(str(status), {})
    return response.get("content", {}).get("application/json", {}).get("schema", {})


def dispatch(name, definition, request, body):
    path, query = dict(request.path_params), dict(request.query_params)
    status = next((int(code) for code in definition["responses"] if code.startswith("2")), 200)
    response = Response(status_code=status)
    if name == "auth_login":
        return auth.login(request, response, body), response
    if name == "auth_me":
        return auth.me(request), response
    principal = auth.authenticate(request, path.get("workspace_id"))
    if name == "auth_logout":
        with transaction() as repo:
            repo.update("app_session", principal.session["id"], revoked_at=now())
        response.delete_cookie(auth.COOKIE, path="/api/pharma")
        response.delete_cookie(auth.CSRF_COOKIE, path="/api/pharma")
        return {"message": "已退出登录"}, response
    with transaction(path["workspace_id"]) as repo:
        key = request.headers.get("idempotency-key")
        existing = None
        operation_id = name + ":" + str(request.url.path)
        if name in IDEMPOTENT:
            require(key and 8 <= len(key) <= 200, "VALIDATION_ERROR", "请提供 8–200 字符的 Idempotency-Key", 422)
            repo.advisory(f"idempotency:{repo.workspace_id}:{principal.user_id}:{operation_id}:{key}")
            records = repo.rows("idempotency_record", actor_id=principal.user_id, operation=operation_id, key=key)
            if records:
                existing = records[0]
                require(existing["request_hash"] == digest(body), "IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同参数", 409)
                response.status_code = existing["response_status"]
                return existing["response_body"], response
        value = api.operation(repo, principal, name, path, query, body, request)
        if name in IDEMPOTENT:
            repo.add("idempotency_record", actor_id=principal.user_id, operation=operation_id, key=key, request_hash=digest(body), response_status=status, response_body=jsonable_encoder(value), expires_at=now() + timedelta(days=7))
        return value, response


def validate_parameters(request, definition):
    root = specification()
    for param in definition.get("parameters", []):
        if "$ref" in param:
            param = root["components"]["parameters"][param["$ref"].split("/")[-1]]
        location, key = param["in"], param["name"]
        value = request.path_params.get(key) if location == "path" else request.query_params.get(key) if location == "query" else request.headers.get(key)
        require(value is not None or not param.get("required"), "VALIDATION_ERROR", f"缺少参数 {key}", 422)
        if value is None:
            continue
        schema = param.get("schema", {})
        try:
            if schema.get("type") == "integer":
                value = int(value)
            if schema.get("type") == "boolean":
                require(value in ("true", "false"), "VALIDATION_ERROR", "无效布尔值", 422)
                value = value == "true"
            jsonschema.Draft202012Validator({**schema, "components": root["components"]}, format_checker=jsonschema.FormatChecker()).validate(value)
        except (ValueError, jsonschema.ValidationError):
            raise PharmaError("VALIDATION_ERROR", f"参数 {key} 无效", 422) from None
    for key, value in request.path_params.items():
        if key.endswith("_id"):
            try:
                UUID(value)
            except ValueError:
                raise PharmaError("NOT_FOUND", "对象不存在或无权访问", 404) from None


async def stream_events(request):
    workspace, run_id = request.path_params["workspace_id"], request.path_params["run_id"]
    try:
        after = int(request.headers.get("last-event-id", request.query_params.get("after", "0")))
        require(after >= 0, "VALIDATION_ERROR", "事件游标无效", 422)
    except ValueError:
        raise PharmaError("VALIDATION_ERROR", "事件游标无效", 422) from None

    def read(cursor):
        principal = auth.authenticate(request, workspace)
        with transaction(workspace) as repo:
            run = api.owned_run(repo, principal, run_id)
            table = repo.table("run_event")
            events = repo.connection.execute(repo.query("run_event", run_id=run_id).where(table.c.seq > cursor).order_by(table.c.seq).limit(200)).mappings().all()
            if cursor and events and events[0]["seq"] > cursor + 1:
                raise PharmaError("EVENT_HISTORY_EXPIRED", "事件历史已过期，请刷新任务详情", 410)
            return run, jsonable_encoder([dict(e) for e in events])

    initial = await anyio.to_thread.run_sync(read, after)

    async def generate():
        cursor, batch = after, initial
        while True:
            run, events = batch
            for event in events:
                cursor = event["seq"]
                payload = {k: event[k] for k in ("schema_version", "run_id", "seq", "occurred_at", "type", "payload")}
                yield f"id: {cursor}\nevent: {event['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if run["status"] in TERMINAL and cursor >= run["next_event_seq"]:
                break
            if await request.is_disconnected():
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(2)
            try:
                batch = await anyio.to_thread.run_sync(read, cursor)
            except PharmaError:
                break

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def endpoint_for(name, definition):
    async def endpoint(request: Request):
        validate_parameters(request, definition)
        if name == "health_liveness":
            return {"status": "ok"}
        if name == "health_readiness":

            def ready():
                from sqlalchemy import text

                with transaction() as repo:
                    repo.connection.execute(text("SELECT 1 FROM alembic_version"))
                return {"status": "ok"}

            return await anyio.to_thread.run_sync(ready)
        if name == "runs_stream":
            return await stream_events(request)
        body = {}
        schema = definition.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
        if schema:
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                require(len(data) <= 1024 * 1024, "VALIDATION_ERROR", "请求正文过大", 413)
            try:
                body = json.loads(data)
            except (ValueError, UnicodeDecodeError):
                raise PharmaError("VALIDATION_ERROR", "JSON 正文无效", 422) from None
            validate(schema["$ref"].split("/")[-1], body)
        value, response = await anyio.to_thread.run_sync(dispatch, name, definition, request, body)
        if name == "reports_export":
            export_format = request.query_params.get("format", "markdown")
            content = json.dumps(value, ensure_ascii=False, indent=2) if export_format == "json" else reports.export_markdown(value)
            return Response(content, media_type="application/json" if export_format == "json" else "text/markdown", headers={"Content-Disposition": f'attachment; filename="pharmascope-report.{"json" if export_format == "json" else "md"}"'})
        value = jsonable_encoder(project(value, response_schema(definition, response.status_code)))
        result = JSONResponse(value, status_code=response.status_code)
        for header, cookie_value in response.raw_headers:
            if header.lower() == b"set-cookie":
                result.raw_headers.append((header, cookie_value))
        if isinstance(value, dict) and "revision" in value:
            result.headers["ETag"] = f'"{value["revision"]}"'
        return result

    endpoint.__name__ = name
    return endpoint


for route, methods in specification()["paths"].items():
    if route == "/healthz":
        route = "/api/pharma/healthz"
    elif route == "/readyz":
        route = "/api/pharma/readyz"
    for method, definition in methods.items():
        if method not in ("get", "post", "patch", "delete"):
            continue
        app.add_api_route(route, endpoint_for(definition["operationId"], definition), methods=[method.upper()], operation_id=definition["operationId"])


@app.middleware("http")
async def errors_and_headers(request, call_next):
    request_id = uid()
    try:
        response = await call_next(request)
    except PharmaError as exc:
        response = JSONResponse({"error": {"code": exc.code, "message": exc.message, "details": exc.details, "request_id": request_id}}, status_code=exc.status)
    except IntegrityError:
        response = JSONResponse({"error": {"code": "CONFLICT", "message": "内容已存在或关联约束不满足", "details": {}, "request_id": request_id}}, status_code=409)
    except SQLAlchemyError:
        logger.error("Pharma database operation failed request_id=%s", request_id)
        response = JSONResponse({"error": {"code": "DATABASE_UNAVAILABLE", "message": "数据库暂时不可用", "details": {}, "request_id": request_id}}, status_code=503)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response
