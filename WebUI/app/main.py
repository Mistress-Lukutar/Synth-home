"""Main FastAPI application factory for the ZigbeeHUB WebUI."""

import asyncio
import json
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles


from app.config import get_settings
from app.dependencies import verify_api_key
from app.exceptions import setup_exception_handlers
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.logging import StructuredLoggingMiddleware
from app.routers import connection, devices, network, panels, graphs, node_registry
from app.services import sse_manager
from app.services.event_bus import EventBus
from app.services.hub_service import HubService

from app.db import engine, async_session
from sqlalchemy import select, text
from app.models.db_models import SystemSetting
from app.scheduler_engine import start_scheduler, stop_scheduler, get_scheduler

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

        # Node registry (populated once at startup)
        from app.services.node_registry import create_node_registry
        node_registry = create_node_registry()
        app.state.node_registry = node_registry

        # Panel state + graph executor
        from app.services.panel_state_service import PanelStateService
        from app.services.graph_executor import GraphExecutor
        from app.db import async_session

        panel_state_service = PanelStateService(event_bus=event_bus)
        app.state.panel_state_service = panel_state_service

        graph_executor = GraphExecutor(
            hub_service=hub_service,
            panel_state_service=panel_state_service,
            node_registry=node_registry,
        )
        app.state.graph_executor = graph_executor

        # Panel trigger service (APScheduler + EventBus integration)
        from app.services.panel_trigger_service import PanelTriggerService

        panel_trigger_service = PanelTriggerService(
            scheduler=get_scheduler(),
            graph_executor=graph_executor,
            event_bus=event_bus,
        )
        app.state.panel_trigger_service = panel_trigger_service
        async with async_session() as db:
            await panel_trigger_service.load_all(db)

        # Bridge domain events to SSE
        for evt in (
            "hub_connected",
            "hub_disconnected",
            "hub_message",
            "hub_serial",
            "panel_output",
        ):
            event_bus.subscribe(evt, lambda p, e=evt: _sse_bridge(e, p))

        # Scheduler
        start_scheduler()

        async def _get_last_port() -> str | None:
            async with async_session() as db:
                result = await db.execute(
                    select(SystemSetting).where(SystemSetting.key == "last_connected_port")
                )
                setting = result.scalar_one_or_none()
                return setting.value if setting else None

        # Auto-connect to configured port if set (inside Uvicorn loop)
        port_to_connect = settings_obj.auto_connect_port
        if not port_to_connect:
            port_to_connect = await _get_last_port()
        if port_to_connect:
            logger.info("auto_connecting_to_port", port=port_to_connect)
            try:
                await hub_service.connect(port_to_connect)
                logger.info("auto_connect_successful", port=port_to_connect)
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
    app.add_middleware(StructuredLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware, max_requests=200, window_seconds=60)
    app.add_middleware(SecurityHeadersMiddleware)

    app.mount("/static", StaticFiles(directory="static"), name="static")
    setup_exception_handlers(app)

    app.include_router(connection, dependencies=[Depends(verify_api_key)])
    app.include_router(devices, dependencies=[Depends(verify_api_key)])
    app.include_router(network, dependencies=[Depends(verify_api_key)])
    app.include_router(panels, dependencies=[Depends(verify_api_key)])
    app.include_router(graphs, dependencies=[Depends(verify_api_key)])
    app.include_router(node_registry, dependencies=[Depends(verify_api_key)])

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

    # SPA fallback — serve built Vue app for all non-API routes
    app.mount("/", StaticFiles(directory="static/dist", html=True), name="spa")

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
