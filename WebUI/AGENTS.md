# ZigbeeHUB WebUI — Agent Guide

This document contains project-specific context for AI coding agents working on the ZigbeeHUB WebUI codebase.

## Project Overview

ZigbeeHUB WebUI is a FastAPI-based web interface for managing a Zigbee coordinator hub over USB Serial. It provides:

- COM-port discovery and connection to the hub
- Real-time device listing and control (on/off/toggle/level/color commands)
- Zigbee network management (permit join)
- Rule-based scenarios with manual, schedule, and device-event triggers
- Server-Sent Events (SSE) for live hub notifications

The frontend is a single-page vanilla JavaScript application served from `templates/index.html` and `static/app.js`.

## Technology Stack

- **Runtime**: Python >= 3.10
- **Web Framework**: FastAPI >= 0.110.0
- **Server**: Uvicorn (with standard extras)
- **Database**: SQLite via `sqlite+aiosqlite` with SQLAlchemy 2.0 async ORM
- **Validation/Config**: Pydantic v2, pydantic-settings
- **Scheduling**: APScheduler 3.x (`AsyncIOScheduler`)
- **Serial Communication**: pyserial
- **Logging**: structlog (structured JSON-like logging)
- **Frontend**: Plain HTML5, CSS, JavaScript (no build step)
- **Build System**: Hatchling (configured in `pyproject.toml`)

## Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app factory, startup/shutdown, SSE endpoint
│   ├── config.py            # Pydantic-settings configuration
│   ├── db.py                # Async SQLAlchemy engine + session factory
│   ├── dependencies.py      # FastAPI dependency injection helpers
│   ├── exceptions.py        # Custom exceptions + exception handlers
│   ├── scheduler_engine.py  # APScheduler integration + scenario execution
│   ├── models/
│   │   ├── __init__.py
│   │   ├── db_models.py     # SQLAlchemy ORM models (DeviceAlias, Scenario)
│   │   └── schemas.py       # Pydantic request/response schemas
│   ├── routers/
│   │   ├── __init__.py      # Aggregates and exports all routers
│   │   ├── connection.py    # /api/ports, /api/connect, /api/disconnect, /api/status
│   │   ├── devices.py       # /api/devices, /api/devices/{ieee}/command, /api/devices/{ieee}/rename
│   │   ├── network.py       # /api/network/permit-join
│   │   └── scenarios.py     # /api/scenarios CRUD + manual trigger
│   └── services/
│       ├── __init__.py
│       ├── hub_client.py    # Low-level pyserial JSON-over-serial client
│       ├── hub_service.py   # Business-logic wrapper around HubClient (singleton)
│       └── sse_manager.py   # SSE broadcast manager
├── static/
│   ├── app.js               # Frontend logic (SPA)
│   └── favicon.svg
├── templates/
│   └── index.html           # Main page with embedded CSS
├── pyproject.toml           # Dependencies, build config, tool settings
├── run.py                   # Entry point: `python run.py`
├── start.bat                # Windows launcher (creates venv, installs, runs)
└── zigbeehub.db             # SQLite database file
```

## Build and Run Commands

### Local Development (Windows)

The easiest way to start on Windows is:

```cmd
start.bat
```

This script will:
1. Create a `.venv` virtual environment if missing
2. Upgrade pip
3. Install the package in editable mode with dev extras (`pip install -e ".[dev]"`)
4. Launch the server via `python run.py`

### Manual Setup

```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Run the server
python run.py
```

### Configuration

Environment variables (optional, read via Pydantic Settings):

- `PORT` — server port (default: `8080`)
- `HOST` — bind host (default: `127.0.0.1`)
- `LOG_LEVEL` — logging level (default: `INFO`)
- `CORS_ORIGINS` — list of allowed CORS origins (default: `["*"]`)
- `AUTO_CONNECT_PORT` — COM port to auto-connect on startup (default: `None`)

You can place these in a `.env` file in the project root.

## Code Style Guidelines

- **Formatter/Linter**: Ruff is configured in `pyproject.toml`.
  - Max line length: `100`
  - Target Python version: `py310`
- **Type hints**: Use typing annotations throughout (the codebase already uses `typing.Annotated`, `Optional`, `List`, etc.).
- **Docstrings**: All modules and public functions have docstrings.
- **Naming**: Follow PEP 8 (`snake_case` for functions/variables, `PascalCase` for classes).
- **Async**: The project is fully async. Database access uses `async_session`, and serial I/O is wrapped with `asyncio.to_thread`.
- **Logging**: Use `structlog.get_logger(__name__)` and log with structured kwargs (e.g., `logger.info("event_name", key=value)`).

## Testing Instructions

There are **no tests in the repository yet**, but the testing toolchain is pre-configured:

- **Framework**: pytest + pytest-asyncio
- **HTTP client for tests**: httpx
- **Config location**: `pyproject.toml`

### Run Tests

```bash
pytest
```

### Add Tests

If you add tests, place them in a `tests/` directory at the project root. Naming convention: `test_*.py`. The project uses `asyncio_mode = "auto"`, so `async` test functions will run without extra decorators.

Recommended areas to test:
- Router endpoints (use `fastapi.testclient.TestClient` or `httpx.AsyncClient` with `ASGITransport`)
- Hub client message parsing and command serialization
- Scheduler engine cron translation and scenario execution logic
- Database model operations via async SQLAlchemy sessions

## Security Considerations

- **CORS**: The default `CORS_ORIGINS` is `["*"]`. In production, restrict this to known origins.
- **Serial Port Access**: The application opens raw COM ports. Ensure the process runs with only the necessary hardware permissions.
- **No Authentication**: The current API is fully open. Do not expose it to untrusted networks without adding an authentication layer.
- **Input Validation**: Pydantic schemas validate request bodies, but JSON fields stored in the database (`trigger_config`, `action_config`) are parsed at runtime. Keep parsing logic defensive (the existing code uses `try/except` around `json.loads`).
- **SQL Injection**: Use SQLAlchemy ORM constructs; avoid raw SQL string concatenation.

## Key Architectural Patterns

1. **Singleton HubService**: `get_hub_service()` returns a single global `HubService` instance that wraps the serial `HubClient`. This avoids multiple concurrent serial connections.
2. **SSE for Real-Time Updates**: The `/events` endpoint streams JSON messages to the frontend. `SSEManager` maintains a list of `asyncio.Queue` instances and broadcasts to all connected clients.
3. **Scenario Engine**: APScheduler runs scheduled scenarios. `load_scheduler_jobs()` is called on startup to restore schedules from the database. Scenarios can also react to device events (`device_joined`, `device_left`, `state_change`, `command_failed`).
4. **Device Aliases**: User-friendly names are stored in the `DeviceAlias` table and merged into the device list returned by the hub firmware.
5. **JSON-over-Serial Protocol**: The hub speaks newline-delimited JSON over USB serial at 115200 baud. Commands look like `{"cmd": "list"}`, `{"cmd": "on", "ieee": "..."}`, etc.

## Agent Workspace

The `.agents/` directory in the project root is reserved for AI agent plans, scripts, and temporary working notes. It is listed in `.gitignore` and must **never** be committed to the repository.

Use it for:
- Step-by-step implementation plans
- Code-review notes and checklists
- Temporary scratchpads during long refactoring sessions

## Notes for Agents

- Do **not** commit the `zigbeehub.db` file unless explicitly asked.
- The frontend is intentionally framework-free. Keep `app.js` and `index.html` self-contained without introducing npm/Webpack unless the user specifically requests it.
- When modifying the serial protocol or database models, update both the backend parser and any affected frontend rendering logic.
- If you add new API endpoints, include them in `app/routers/__init__.py` and wire them into `app/main.py`.
