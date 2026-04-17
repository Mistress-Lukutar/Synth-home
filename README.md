# Synth-home

Web interface for managing a Zigbee coordinator hub over USB Serial. FastAPI backend + Vue 3 SPA frontend.

## Features

- **COM-port discovery** and real-time hub connection management
- **Device listing** with friendly aliases, inline renaming, and on/off toggle
- **Device control** — on / off / toggle / level / color commands
- **Zigbee network management** — permit joining for new devices
- **Rule-based scenarios** with manual, schedule (cron), and device-event triggers
- **Drag-and-drop** scenario reordering with persistent sort order
- **Inline scenario editing** (trigger, action, target device, schedule)
- **Server-Sent Events (SSE)** for live hub notifications
- **APScheduler** for cron-based scenario execution
- **API Key authentication** + rate limiting + security headers

## Tech Stack

### Backend
- **Python** >= 3.10
- **FastAPI** >= 0.110.0
- **Uvicorn**
- **SQLite** (`sqlite+aiosqlite`) + SQLAlchemy 2.0 async ORM + Alembic migrations
- **Pydantic v2** + pydantic-settings
- **APScheduler** 3.x (`AsyncIOScheduler`)
- **pyserial** for USB Serial communication
- **structlog** for structured logging

### Frontend
- **Vue 3** + **Vite** + **TypeScript**
- **Pinia-like store** (`useHubStore`) — centralized reactive state
- Component architecture: `DashboardPage`, `ScenariosPage`, `DeviceCard`, `ScenarioCard`, `EventLog`

## Quick Start (Windows)

```cmd
start.bat
```

What it does:
1. Creates `.venv` (if missing)
2. Installs dependencies (`pip install -e ".[dev]"`)
3. Builds the frontend (`npm install && npm run build`)
4. Applies Alembic migrations
5. Starts the server on `0.0.0.0:8080`

## Manual Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# Build frontend
cd frontend
npm install
npm run build
cd ..

# Run database migrations
python -m alembic upgrade head

# Start server
python run.py
```

## Docker

```bash
docker compose up --build
```

## Configuration

Environment variables (or `.env` in project root):

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Server port |
| `HOST` | `0.0.0.0` | Bind host |
| `LOG_LEVEL` | `INFO` | Logging level |
| `CORS_ORIGINS` | `[]` | Allowed CORS origins |
| `API_KEY` | `dev-key` | API authorization key (`X-API-Key` header) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./zigbeehub.db` | SQLite database URL |

## Project Structure

```
app/
  main.py              # FastAPI app factory + lifespan
  config.py            # Pydantic-settings configuration
  db.py                # Async SQLAlchemy engine + session factory
  dependencies.py      # DI helpers
  exceptions.py        # Custom exceptions + handlers
  middleware/          # RateLimit, SecurityHeaders, StructuredLogging
  models/
    db_models.py       # SQLAlchemy ORM models
    schemas.py         # Pydantic schemas
  repositories/        # Repository layer (Device, Scenario, Alias)
  routers/
    connection.py      # /api/ports, /api/connect, /api/disconnect, /api/status
    devices.py         # /api/devices, commands, rename
    network.py         # /api/network/permit-join
    scenarios.py       # /api/scenarios CRUD + trigger + reorder
  services/
    hub_client.py      # pyserial JSON-over-serial client
    hub_service.py     # Business logic + DB sync
    event_bus.py       # Internal event bus
    sse_manager.py     # SSE broadcast manager
    scenario_service.py # Scenario execution engine
frontend/
  src/
    components/        # Vue components
    composables/       # useHubStore, etc.
    api.ts             # HTTP client
static/dist/         # Built frontend (mounted as SPA)
```

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/ports` | GET | List available COM ports |
| `/api/connect` | POST | Connect to hub |
| `/api/disconnect` | POST | Disconnect from hub |
| `/api/status` | GET | Connection status |
| `/api/devices` | GET | List Zigbee devices |
| `/api/devices/{ieee}/command` | POST | Send command to device |
| `/api/devices/{ieee}/rename` | PATCH | Rename device alias |
| `/api/network/permit-join` | POST | Open network for joining |
| `/api/scenarios` | GET / POST | List / create scenarios |
| `/api/scenarios/reorder` | PATCH | Reorder scenarios |
| `/api/scenarios/{id}` | PATCH / DELETE | Update / delete scenario |
| `/api/scenarios/{id}/trigger` | POST | Manually trigger a scenario |
| `/events` | GET | SSE stream for real-time events |

All endpoints (except `/health` and SSE `/events`) require the `X-API-Key` header.

## Security

- API Key authentication via `X-API-Key` header
- Rate limiting middleware (30 req/min default)
- Security headers (X-Content-Type-Options, X-Frame-Options, etc.)
- CORS configured via `CORS_ORIGINS`

## License

MIT
