"""Main FastAPI application factory for the ZigbeeHUB WebUI."""

import asyncio
import json

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.exceptions import setup_exception_handlers
from app.routers import connection, devices, network, scenarios
from app.services import sse_manager
from app.services.hub_service import get_hub_service
from app.scheduler_engine import start_scheduler, stop_scheduler, load_scheduler_jobs
from app.db import engine, Base

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="ZigbeeHUB WebUI",
        description="Web interface for ZigbeeHUB over USB Serial",
        version="0.1.0",
    )

    app.mount("/static", StaticFiles(directory="static"), name="static")
    setup_exception_handlers(app)

    app.include_router(connection)
    app.include_router(devices)
    app.include_router(network)
    app.include_router(scenarios)

    templates = Jinja2Templates(directory="templates")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """Serve the main HTML page."""
        return templates.TemplateResponse(request, "index.html")

    @app.get("/events")
    async def events(request: Request) -> StreamingResponse:
        """Server-Sent Events stream for real-time hub notifications."""
        queue = sse_manager.subscribe()

        async def event_generator():
            try:
                while True:
                    msg = await queue.get()
                    yield f"data: {json.dumps(msg)}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                sse_manager.unsubscribe(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    @app.on_event("startup")
    async def on_startup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        start_scheduler()
        await load_scheduler_jobs()

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        stop_scheduler()
        service = get_hub_service()
        if service.is_connected():
            await service.disconnect()

    logger.info("fastapi_application_created")
    return app


def main() -> None:
    """Run the application with uvicorn server."""
    import uvicorn

    settings_obj = get_settings()
    import logging

    logging.basicConfig(level=getattr(logging, settings_obj.log_level.upper()))

    # Auto-connect to configured port if set
    if settings_obj.auto_connect_port:
        service = get_hub_service()
        logger.info("auto_connecting_to_configured_port", port=settings_obj.auto_connect_port)
        try:
            asyncio.run(service.connect(settings_obj.auto_connect_port))
            logger.info("auto_connect_successful", port=settings_obj.auto_connect_port)
        except Exception as e:
            logger.warning("auto_connect_failed", error=str(e))

    logger.info("starting_uvicorn_server", host=settings_obj.host, port=settings_obj.port)
    uvicorn.run(
        "app.main:create_app",
        host=settings_obj.host,
        port=settings_obj.port,
        factory=True,
        reload=False,
    )


if __name__ == "__main__":
    main()
