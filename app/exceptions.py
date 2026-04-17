"""Custom exceptions and exception handlers for the ZigbeeHUB WebUI."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class HubError(Exception):
    """Base exception for hub-related errors."""

    def __init__(self, message: str = "Hub error") -> None:
        self.message = message
        super().__init__(self.message)


class HubConnectionError(HubError):
    """Raised when connection to the hub fails."""

    def __init__(self, message: str = "Not connected to hub") -> None:
        super().__init__(message)


class HubCommandError(HubError):
    """Raised when a command to the hub fails."""

    def __init__(self, message: str = "Command failed") -> None:
        super().__init__(message)


def setup_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers on the FastAPI application."""

    @app.exception_handler(HubConnectionError)
    async def hub_connection_error_handler(
        request: Request, exc: HubConnectionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": exc.message},
        )

    @app.exception_handler(HubCommandError)
    async def hub_command_error_handler(
        request: Request, exc: HubCommandError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": exc.message},
        )

    @app.exception_handler(HubError)
    async def hub_error_handler(request: Request, exc: HubError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": exc.message},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Internal server error"},
        )
