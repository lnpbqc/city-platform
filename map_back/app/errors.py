"""Shared HTTP errors and request correlation without changing legacy detail."""
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException as FastAPIHTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .contracts import ErrorEnvelope

logger = logging.getLogger("city.api")
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())
ERROR_RESPONSES = {status: {"model": ErrorEnvelope} for status in (400, 403, 404, 409, 413, 422, 500)}


class ApiProblem(FastAPIHTTPException):
    def __init__(self, status_code: int, code: str, message: str, detail=None):
        super().__init__(status_code, message if detail is None else detail)
        self.code = code
        self.message = message


class TraceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        trace_id = uuid4().hex
        scope.setdefault("state", {})["trace_id"] = trace_id
        started = perf_counter()
        status = 500

        async def traced_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [(key, value) for key, value in message.get("headers", [])
                                      if key.lower() != b"x-trace-id"]
                message["headers"].append((b"x-trace-id", trace_id.encode("ascii")))
            await send(message)

        try:
            await self.app(scope, receive, traced_send)
        finally:
            logger.info("trace_id=%s method=%s path=%s status=%s duration_ms=%.2f",
                        trace_id, scope["method"], scope["path"], status, (perf_counter() - started) * 1000)


def response(request: Request, status: int, code: str, message: str, detail, headers=None):
    trace_id = getattr(request.state, "trace_id", uuid4().hex)
    return JSONResponse(status_code=status, content=jsonable_encoder({
        "code": code, "message": message, "detail": detail, "trace_id": trace_id,
    }), headers={**(headers or {}), "X-Trace-ID": trace_id})


async def http_error(request: Request, error: HTTPException):
    detail = error.detail
    message = detail.get("message", "请求失败") if isinstance(detail, dict) else str(detail)
    code = {400: "INVALID_ARGUMENT", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 422: "CONTENT_INVALID"}.get(error.status_code, "HTTP_ERROR")
    if error.status_code == 404:
        for resource, name in (("assets", "ASSET"), ("layers", "LAYER"), ("bookmarks", "BOOKMARK")):
            if request.url.path.startswith(f"/api/{resource}/"):
                code = f"{name}_NOT_FOUND"
                break
    if error.status_code == 409 and isinstance(detail, dict) and "references" in detail:
        code = "ASSET_IN_USE"
    return response(request, error.status_code, getattr(error, "code", code),
                    getattr(error, "message", message), detail, error.headers)


async def validation_error(request: Request, error: RequestValidationError):
    detail = error.errors()
    message = "；".join(item["msg"] for item in detail)
    return response(request, 422, "VALIDATION_ERROR", message, detail)


async def unexpected_error(request: Request, error: Exception):
    trace_id = getattr(request.state, "trace_id", "unknown")
    logger.error("trace_id=%s unhandled request error", trace_id,
                 exc_info=(type(error), error, error.__traceback__))
    return response(request, 500, "INTERNAL_ERROR", "服务处理失败，请使用 trace_id 查询日志", "服务内部错误")
