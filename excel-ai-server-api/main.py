from contextlib import asynccontextmanager
import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import LANGFUSE_AVAILABLE, langfuse_client
from app.core import DatabaseManager
from app.routers import (
    admin,
    auth,
    boards,
    categories,
    chat,
    dashboard,
    etl,
    export,
    files,
    health,
    langfuse_share,
    preview,
    projects,
    query,
    workspace,
)
from app.services.langfuse_sso import bootstrap_langfuse_admin
from app.utils.logging import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared services on startup and flush observability on shutdown."""
    DatabaseManager()

    try:
        await bootstrap_langfuse_admin()
    except Exception as bootstrap_err:
        logger.warning("[lifespan] Langfuse bootstrap failed: %s", bootstrap_err)

    langfuse_startup_check = os.getenv("LANGFUSE_STARTUP_CHECK", "true").strip().lower() in {"1", "true", "yes", "on"}
    langfuse_startup_timeout = float(os.getenv("LANGFUSE_STARTUP_TIMEOUT_SEC", "3"))

    if langfuse_startup_check and LANGFUSE_AVAILABLE and langfuse_client is not None:
        try:
            ok = await asyncio.wait_for(
                asyncio.to_thread(langfuse_client.auth_check),
                timeout=langfuse_startup_timeout,
            )
            if ok:
                logger.info("Langfuse connected")
            else:
                logger.warning("Langfuse auth_check() returned False")
        except TimeoutError:
            logger.warning(
                "Langfuse startup check timed out after %.1fs (host may be unreachable)",
                langfuse_startup_timeout,
            )
        except Exception as lf_err:
            logger.warning("Langfuse startup check failed: %s", lf_err)
    elif not langfuse_startup_check:
        logger.info("Langfuse startup check disabled by LANGFUSE_STARTUP_CHECK")

    yield

    if LANGFUSE_AVAILABLE and langfuse_client is not None:
        try:
            langfuse_client.flush()
            logger.info("Langfuse flush completed")
        except Exception as lf_err:
            logger.warning("Langfuse flush failed: %s", lf_err)


app = FastAPI(
    title="Excel Analysis API",
    description="FastAPI backend for Excel file processing and analysis",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers already define their own prefixes/tags.
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(boards.router)
app.include_router(categories.router)
app.include_router(chat.router)
app.include_router(dashboard.router)
app.include_router(etl.router)
app.include_router(export.router)
app.include_router(files.router)
app.include_router(health.router)
app.include_router(langfuse_share.router)
app.include_router(preview.router)
app.include_router(projects.router)
app.include_router(query.router)
app.include_router(workspace.router)

logger.info("All modular routers registered successfully")
