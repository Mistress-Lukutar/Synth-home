# Synth-home / ZigbeeHUB

A complete Zigbee coordinator hub: ESP32-C6 firmware plus a FastAPI/Vue web interface.

- **Firmware** (`firmware/`) — ESP-IDF 5.5.1 project for ESP32-C6. Runs the Zigbee coordinator, exposes a USB Serial JSON command interface, an HTTP REST API, and a WebSocket event stream.
- **WebUI** (`WebUI/`) — FastAPI backend + Vue 3 SPA frontend for discovering, controlling, and automating Zigbee devices through the hub.

## Repository Layout

```
.
├── AGENTS.md          # AI agent instructions for the whole repo
├── README.md          # This file
├── firmware/          # ESP-IDF Zigbee coordinator firmware
│   ├── main/main.c
│   ├── components/    # Custom IDF components
│   ├── sdkconfig
│   └── AGENTS.md      # Firmware-specific agent guide
└── WebUI/             # FastAPI web application
    ├── app/           # Python backend
    ├── frontend/      # Vue 3 + Vite frontend
    ├── tests/
    ├── README.md      # WebUI-specific setup guide
    └── AGENTS.md      # WebUI-specific agent guide
```

## How the Pieces Connect

1. The **firmware** forms a Zigbee network as a coordinator and keeps a device table in NVS.
2. The **WebUI** connects to the firmware either:
   - over USB Serial (the original mode) — see `WebUI/app/services/hub_client.py`, or
   - over Wi-Fi via the firmware's HTTP/WebSocket API.
3. Commands from the WebUI are sent as JSON; the firmware broadcasts device join/leave/state-change events back.

## Quick Start

### Firmware

Prerequisites: ESP-IDF 5.5.1 installed, target set to `esp32c6`.

```bash
cd firmware
idf.py set-target esp32c6
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

For Windows PowerShell setup with ESP-IDE, see `firmware/AGENTS.md`.

### WebUI

See `WebUI/README.md` for the full guide. The short version on Windows:

```cmd
cd WebUI
start.bat
```

Or manually:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

cd frontend
npm install
npm run build
cd ..

python -m alembic upgrade head
python run.py
```

The server starts on `http://0.0.0.0:8080` by default.

## Documentation

- `firmware/AGENTS.md` — firmware architecture, component graph, build commands, and runtime details.
- `WebUI/README.md` — WebUI features, tech stack, API overview, and configuration.
- `WebUI/AGENTS.md` and `AGENTS.md` — AI agent guides for the respective scopes.

## License

MIT
