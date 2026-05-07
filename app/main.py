from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import build_sessionmaker
from app.services.bootstrap import ensure_bootstrap_admin
from app.services.identity import DisabledIdentityProvider
from app.services.litellm import LiteLLMClient
from app.web.routes import router


def create_app(settings: Settings | None = None, litellm_client: LiteLLMClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    session_local = build_sessionmaker(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_create_tables:
            Base.metadata.create_all(bind=session_local.kw["bind"])
        with session_local() as db:
            ensure_bootstrap_admin(db, settings)
        yield

    app = FastAPI(title="LiteLLM Team Key Delegation Service", lifespan=lifespan)
    app.state.settings = settings
    app.state.SessionLocal = session_local
    app.state.identity_provider = DisabledIdentityProvider()
    app.state.litellm_client = litellm_client or LiteLLMClient(settings.litellm_base_url, settings.litellm_master_key)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        same_site="lax",
        https_only=settings.cookie_secure,
        max_age=60 * 60 * 12,
    )
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(router)
    return app


app = create_app()
