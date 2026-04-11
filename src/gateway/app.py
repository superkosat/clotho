import logging
from contextlib import asynccontextmanager

import setproctitle
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from exceptions.base import ClothoException
from gateway.auth.dependencies import require_token
from gateway.config import settings
from gateway.session import SessionManager
from gateway.routes import health, chats, config, agent, permissions, profiles, sandbox
from mcp_client import MCPManager


async def clotho_exception_handler(_request: Request, exc: ClothoException) -> JSONResponse:
    """Convert ClothoException to structured JSON response.

    Returns 500 by default - route handlers should catch and re-raise
    with appropriate HTTP status codes for their context.
    """
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": exc.message,
        }
    )


async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert Pydantic validation errors to user-friendly messages."""
    errors = exc.errors()
    if errors:
        # Extract the first error's message
        err = errors[0]
        loc = " -> ".join(str(x) for x in err.get("loc", []) if x != "body")
        msg = err.get("msg", "Invalid input")
        message = f"{loc}: {msg}" if loc else msg
    else:
        message = "Invalid request data"

    return JSONResponse(
        status_code=422,
        content={
            "error": "ValidationError",
            "message": message,
        }
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger("mcp_client").setLevel(logging.INFO)
    setproctitle.setproctitle("clotho-gateway")
    mcp_manager = MCPManager()
    await mcp_manager.start()
    app.state.session_manager = SessionManager(mcp_manager=mcp_manager)
    yield
    await mcp_manager.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Clotho Agent API", version="0.1.0", lifespan=lifespan)

    app.add_exception_handler(ClothoException, clotho_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(chats.router, dependencies=[Depends(require_token)])
    app.include_router(config.router, dependencies=[Depends(require_token)])
    app.include_router(agent.router)
    app.include_router(permissions.router, dependencies=[Depends(require_token)])
    app.include_router(profiles.router, dependencies=[Depends(require_token)])
    app.include_router(sandbox.router, dependencies=[Depends(require_token)])

    return app
