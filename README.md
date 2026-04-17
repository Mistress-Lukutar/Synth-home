# ZigbeeHUB WebUI

FastAPI-based web interface for managing a Zigbee coordinator hub over USB Serial.

## Features

- **COM-port discovery** and real-time connection management
- **Device listing** with user-friendly aliases and inline renaming
- **Device control** — on / off / toggle / level / color commands
- **Zigbee network management** — permit joining
- **Rule-based scenarios** with manual, schedule, and device-event triggers
- **Server-Sent Events (SSE)** for live hub notifications
- **APScheduler** for cron-based scenario execution

## Tech Stack

- **Python** >= 3.10
- **FastAPI** >= 0.110.0
- **Uvicorn** (with standard extras)
- **SQLite** via `sqlite+aiosqlite` with SQLAlchemy 2.0 async ORM
- **Pydantic v2** + pydantic-settings
- **APScheduler** 3.x (`AsyncIOScheduler`)
- **pyserial** for USB Serial communication
- **structlog** for structured logging
- **Vanilla JS** frontend (no build step)

## Quick Start (Windows)

```cmd
start.bat
```

This will:
1. Create a `.venv` virtual environment (if missing)
2. Install dependencies in editable mode
3. Launch the server

## Manual Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python run.py
```

## Configuration

Optional environment variables (or `.env` file in project root):

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Server port |
| `HOST` | `127.0.0.1` | Bind host |
| `LOG_LEVEL` | `INFO` | Logging level |
| `CORS_ORIGINS` | `["*"]` | Allowed CORS origins |
| `AUTO_CONNECT_PORT` | — | COM port to auto-connect on startup |
| `DATABASE_URL` | `sqlite+aiosqlite:///./zigbeehub.db` | SQLite database URL |

## Project Structure

```
app/
  main.py              # FastAPI app factory
  config.py            # Pydantic-settings configuration
  db.py                # Async SQLAlchemy engine + session factory
  dependencies.py      # FastAPI dependency injection helpers
  exceptions.py        # Custom exceptions + exception handlers
  scheduler_engine.py  # APScheduler integration + scenario execution
  models/
    db_models.py       # SQLAlchemy ORM models
    schemas.py         # Pydantic request/response schemas
  routers/
    connection.py      # /api/ports, /api/connect, /api/disconnect, /api/status
    devices.py         # /api/devices, device commands, rename
    network.py         # /api/network/permit-join
    scenarios.py       # /api/scenarios CRUD + manual trigger
  services/
    hub_client.py      # Low-level pyserial JSON-over-serial client
    hub_service.py     # Business-logic wrapper around HubClient
    sse_manager.py     # SSE broadcast manager
static/
  app.js               # Frontend SPA logic
  favicon.svg
templates/
  index.html           # Main page with embedded CSS
```

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ports` | GET | List available COM ports |
| `/api/connect` | POST | Connect to hub on a COM port |
| `/api/disconnect` | POST | Disconnect from hub |
| `/api/status` | GET | Connection status |
| `/api/devices` | GET | List Zigbee devices |
| `/api/devices/{ieee}/command` | POST | Send command to device |
| `/api/devices/{ieee}/rename` | PATCH | Rename device alias |
| `/api/network/permit-join` | POST | Open network for joining |
| `/api/scenarios` | GET / POST | List / create scenarios |
| `/api/scenarios/{id}` | PATCH / DELETE | Update / delete scenario |
| `/api/scenarios/{id}/trigger` | POST | Manually trigger a scenario |
| `/events` | GET | SSE stream for real-time events |

## Testing

```bash
pytest
```

Tests cover:
- Router endpoints (connection, scenarios)
- HubClient message parsing
- SSEManager broadcast behavior

## Security Notes

- Default CORS is `["*"]` — restrict in production.
- The API has **no authentication** — do not expose to untrusted networks.
- Serial port access requires appropriate hardware permissions.

## License

MIT
