"""Main FastAPI application factory for the ZigbeeHUB WebUI."""

import asyncio
import json
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.dependencies import verify_api_key
from app.exceptions import setup_exception_handlers
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import connection, devices, network, scenarios
from app.services import sse_manager
from app.services.event_bus import EventBus
from app.services.hub_service import HubService
from app.services.scenario_service import ScenarioService
from app.db import engine
from sqlalchemy import text
from app.scheduler_engine import start_scheduler, stop_scheduler, load_scheduler_jobs, set_scenario_service, get_scheduler

logger = structlog.get_logger(__name__)


def configure_logging(log_level: str) -> None:
    """Configure structlog and stdlib logging (call once at startup)."""
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
    import logging

    logging.basicConfig(level=getattr(logging, log_level.upper()))


def _sse_bridge(event_type: str, payload: dict) -> None:
    """Bridge domain events to SSE manager (non-blocking)."""
    asyncio.create_task(sse_manager.broadcast(event_type, payload))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings_obj = get_settings()
    configure_logging(settings_obj.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Domain event bus
        event_bus = EventBus()
        app.state.event_bus = event_bus

        # Hub service (stateful singleton bound to app lifespan)
        hub_service = HubService(event_bus=event_bus)
        app.state.hub_service = hub_service

        # Scenario service
        scenario_service = ScenarioService(
            event_bus=event_bus,
            hub_service=hub_service,
            scheduler=get_scheduler(),
        )
        app.state.scenario_service = scenario_service
        set_scenario_service(scenario_service)

        # Bridge domain events to SSE
        for evt in (
            "hub_connected",
            "hub_disconnected",
            "hub_message",
            "scenario_triggered",
            "scenario_executed",
            "scenario_execution_failed",
            "scenario_skipped",
        ):
            event_bus.subscribe(evt, lambda p, e=evt: _sse_bridge(e, p))

        # Scheduler
        start_scheduler()
        await load_scheduler_jobs()

        # Auto-connect to configured port if set (inside Uvicorn loop)
        if settings_obj.auto_connect_port:
            logger.info("auto_connecting_to_configured_port", port=settings_obj.auto_connect_port)
            try:
                await hub_service.connect(settings_obj.auto_connect_port)
                logger.info("auto_connect_successful", port=settings_obj.auto_connect_port)
            except Exception as e:
                logger.warning("auto_connect_failed", error=str(e))

        yield

        # Shutdown
        stop_scheduler()
        await hub_service.disconnect()

    app = FastAPI(
        title="ZigbeeHUB WebUI",
        description="Web interface for ZigbeeHUB over USB Serial",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings_obj.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware, max_requests=30, window_seconds=60)
    app.add_middleware(SecurityHeadersMiddleware)

    app.mount("/static", StaticFiles(directory="static"), name="static")
    setup_exception_handlers(app)

    app.include_router(connection, dependencies=[Depends(verify_api_key)])
    app.include_router(devices, dependencies=[Depends(verify_api_key)])
    app.include_router(network, dependencies=[Depends(verify_api_key)])
    app.include_router(scenarios, dependencies=[Depends(verify_api_key)])

    templates = Jinja2Templates(directory="templates")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """Serve the main HTML page."""
        return templates.TemplateResponse(request, "index.html")

    @app.get("/health")
    async def health(request: Request) -> dict:
        """Health check endpoint for monitoring."""
        hub = request.app.state.hub_service
        db_ok = False
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            pass
        return {
            "status": "healthy" if db_ok else "degraded",
            "database": "up" if db_ok else "down",
            "hub_connected": hub.is_connected(),
            "hub_port": hub.get_port(),
        }

    @app.get("/events", dependencies=[Depends(verify_api_key)])
    async def events(request: Request) -> StreamingResponse:
        """Server-Sent Events stream for real-time hub notifications."""
        queue = sse_manager.subscribe()

        async def event_generator():
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=25.0)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
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

    logger.info("fastapi_application_created")
    return app


def main() -> None:
    """Run the application with uvicorn server."""
    import uvicorn

    settings_obj = get_settings()
    configure_logging(settings_obj.log_level)

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
