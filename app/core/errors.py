import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def install_exception_handlers(app: FastAPI) -> None:
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
