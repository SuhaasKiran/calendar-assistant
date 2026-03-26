from contextlib import asynccontextmanager
import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.config import get_settings
from app.core.errors import AppError, map_exception_code
from app.core.request_context import get_request_id, set_request_id
from app.db.session import init_db
from app.observability import configure_langsmith_from_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_langsmith_from_settings(get_settings())
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        set_request_id(request_id)
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @application.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError):
        request_id = get_request_id()
        logger.warning(
            "app_error code=%s status=%s request_id=%s msg=%s",
            exc.code,
            exc.status_code,
            request_id,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.public_message(),
                "code": exc.code,
                "request_id": request_id,
                "retryable": exc.retryable,
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, exc: RequestValidationError):
        request_id = get_request_id()
        logger.info("validation_error request_id=%s errors=%s", request_id, exc.errors())
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Request validation failed",
                "code": "VALIDATION_ERROR",
                "request_id": request_id,
                "retryable": False,
            },
        )

    @application.exception_handler(HTTPException)
    async def handle_http_exception(_request: Request, exc: HTTPException):
        request_id = get_request_id()
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        logger.info(
            "http_exception status=%s request_id=%s detail=%s",
            exc.status_code,
            request_id,
            detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": detail,
                "code": "HTTP_ERROR",
                "request_id": request_id,
                "retryable": False,
            },
        )

    @application.exception_handler(Exception)
    async def handle_uncaught_exception(_request: Request, exc: Exception):
        request_id = get_request_id()
        logger.exception(
            "uncaught_exception code=%s request_id=%s",
            map_exception_code(exc),
            request_id,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Something went wrong on our side. Please try again.",
                "code": "INTERNAL_ERROR",
                "request_id": request_id,
                "retryable": False,
            },
        )

    application.include_router(health_router, tags=["health"])
    application.include_router(auth_router)
    application.include_router(chat_router)
    return application


app = create_app()
