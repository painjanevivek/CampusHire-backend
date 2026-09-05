import logging
import re
from json import dumps
from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
logger = logging.getLogger(__name__)


class RequestBodyLimitMiddleware:
    """Reject oversized multipart bodies before Starlette spools upload content."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT"}:
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        settings = get_settings()
        limit: int | None = None
        if path == "/api/v1/resumes":
            limit = settings.resume_max_bytes + settings.request_body_overhead_bytes
        elif path == "/api/v1/profile/photo":
            limit = 2 * 1024 * 1024 + settings.request_body_overhead_bytes
        elif path.endswith("/roster-imports/preview"):
            limit = settings.roster_max_bytes + settings.request_body_overhead_bytes
        if limit is None:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None and int(content_length) > limit:
            await self._reject(send, self._correlation_id(scope))
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise ValueError("request_body_too_large")
            return message

        try:
            await self.app(scope, limited_receive, send)
        except ValueError as error:
            if str(error) != "request_body_too_large":
                raise
            await self._reject(send, self._correlation_id(scope))

    @staticmethod
    def _correlation_id(scope: Scope) -> str:
        state = scope.setdefault("state", {})
        correlation_id = state.get("correlation_id")
        if not correlation_id:
            correlation_id = str(uuid4())
            state["correlation_id"] = correlation_id
        return str(correlation_id)

    @staticmethod
    async def _reject(send: Send, correlation_id: str) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"x-request-id", correlation_id.encode("ascii")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": dumps(
                    {
                        "error": {
                            "code": "request_body_too_large",
                            "message": "Upload is too large.",
                            "correlation_id": correlation_id,
                        }
                    },
                    separators=(",", ":"),
                ).encode("utf-8"),
            }
        )


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_id = request.headers.get("X-Request-ID", "")
        correlation_id = supplied_id if REQUEST_ID_PATTERN.fullmatch(supplied_id) else str(uuid4())
        request.state.correlation_id = correlation_id
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "http_request_failed",
                extra={
                    "event": "http_request_completed",
                    "correlation_id": correlation_id,
                    "http_method": request.method,
                    "route": self._route_template(request),
                    "status_code": 500,
                    "duration_ms": round((perf_counter() - started) * 1_000),
                },
            )
            raise
        response.headers["X-Request-ID"] = correlation_id
        logger.info(
            "http_request_completed",
            extra={
                "event": "http_request_completed",
                "correlation_id": correlation_id,
                "http_method": request.method,
                "route": self._route_template(request),
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1_000),
            },
        )
        return response

    @staticmethod
    def _route_template(request: Request) -> str:
        route = request.scope.get("route")
        return str(getattr(route, "path", "<unmatched>"))


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        if get_settings().app_env in {"staging", "production"}:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
