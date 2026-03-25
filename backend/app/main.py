from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.config import get_settings
from app.db.session import init_db
from app.observability import configure_langsmith_from_settings


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
    application.include_router(health_router, tags=["health"])
    application.include_router(auth_router)
    application.include_router(chat_router)
    return application


app = create_app()
