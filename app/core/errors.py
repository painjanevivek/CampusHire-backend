import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def expected_http_error(request: Request, error: HTTPException) -> JSONResponse:
        correlation_id = request.state.correlation_id
        details: dict[str, object]
        if isinstance(error.detail, dict):
            code = str(error.detail.get("code", "http_error"))
            message = str(error.detail.get("message", "CampusHire could not complete the request."))
            details = {
                key: value for key, value in error.detail.items() if key not in {"code", "message"}
            }
        else:
            code_by_status = {
                401: "unauthenticated",
                403: "forbidden",
                404: "not_found",
                409: "conflict",
                422: "validation_error",
                429: "rate_limited",
                503: "dependency_unavailable",
            }
            code = code_by_status.get(error.status_code, "http_error")
            message = str(error.detail)
            details = {}
        return JSONResponse(
            status_code=error.status_code,
            headers={**(error.headers or {}), "X-Request-ID": correlation_id},
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "correlation_id": correlation_id,
                    **({"details": details} if details else {}),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        correlation_id = request.state.correlation_id
        safe_errors = [
            {
                "location": [str(part) for part in item.get("loc", ())],
                "type": str(item.get("type", "validation_error")),
                "message": str(item.get("msg", "Invalid value")),
            }
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            headers={"X-Request-ID": correlation_id},
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Review the highlighted fields and try again.",
                    "correlation_id": correlation_id,
                    "details": {"errors": safe_errors},
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        correlation_id = request.state.correlation_id
        logger.exception(
            "Unhandled request error",
            exc_info=error,
            extra={"correlation_id": correlation_id},
        )
        return JSONResponse(
            status_code=500,
            headers={"X-Request-ID": correlation_id},
            content={
                "error": {
                    "code": "internal_error",
                    "message": "CampusHire could not complete the request.",
                    "correlation_id": correlation_id,
                }
            },
        )
