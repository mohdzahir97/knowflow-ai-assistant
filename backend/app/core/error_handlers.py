"""Global FastAPI exception handlers.

Ensures every error — expected (`AppError`) or unexpected — is returned to
the client in the standard `APIResponse` envelope, and that stack traces
are never leaked. All exceptions are logged with full detail server-side.
"""
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.core.logging import get_logger, log_extra
from app.schemas.common import APIResponse

logger = get_logger("app.errors")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = _request_id(request)
        logger.warning(
            "Application error",
            extra=log_extra(error_type=type(exc).__name__, status_code=exc.status_code, path=request.url.path),
        )
        response = APIResponse.fail(request_id=request_id, message=exc.message, errors=[exc.message])
        return JSONResponse(status_code=exc.status_code, content=response.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = _request_id(request)
        errors = [f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()]
        logger.warning("Validation error", extra=log_extra(errors=errors, path=request.url.path))
        response = APIResponse.fail(request_id=request_id, message="Validation failed.", errors=errors)
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=response.model_dump(mode="json"))

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = _request_id(request)
        logger.warning("HTTP exception", extra=log_extra(status_code=exc.status_code, detail=exc.detail, path=request.url.path))
        response = APIResponse.fail(request_id=request_id, message=str(exc.detail), errors=[str(exc.detail)])
        return JSONResponse(status_code=exc.status_code, content=response.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        logger.exception("Unhandled exception", extra=log_extra(path=request.url.path))
        response = APIResponse.fail(
            request_id=request_id,
            message="An internal server error occurred.",
            errors=["Internal server error."],
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=response.model_dump(mode="json"))
