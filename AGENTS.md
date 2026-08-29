# AGENTS.md - ZigbeeHUB

## Firmware Project Details

The firmware is an **ESP-IDF v6.0.2** project targeting **ESP32-C6**.

### Actual Directory Layout
```
ZigbeeHUB/
├── .agents/                # Temporary scripts and WIP files
├── AGENTS.md               # This file
├── firmware/               # ESP-IDF firmware project
│   ├── CMakeLists.txt          # Project-level CMake
│   ├── sdkconfig               # Project configuration (auto-generated for ESP32-C6)
│   ├── main/                   # Main application component
│   │   ├── CMakeLists.txt
│   │   └── main.c
│   ├── components/             # Custom IDF components
│   └── build/                  # Build artifacts (gitignored)
└── WebUI/                  # FastAPI web application (Python)
```

### Adding a New Component

Create a directory under `firmware/components/` with the following structure:

```
firmware/components/<component_name>/
├── CMakeLists.txt
├── Kconfig                 # (optional) component configuration
├── include/
│   └── <component_name>.h
└── <component_name>.c
```

**`CMakeLists.txt` template:**
```cmake
idf_component_register(
    SRCS "<component_name>.c"
    INCLUDE_DIRS "include"
    REQUIRES "esp_event" "nvs_flash"        # public dependencies
    PRIV_REQUIRES "driver"                  # private dependencies
)
```

**Registration in `firmware/main/CMakeLists.txt`:**
Add the component name to `REQUIRES` or `PRIV_REQUIRES`:
```cmake
idf_component_register(
    SRCS main.c
    REQUIRES "my_component"
)
```

### Key ESP-IDF Components Used
- `nvs_flash` — Non-volatile settings storage
- `esp_event` — Inter-component event bus
- `esp_zigbee` / `esp_zboss` — Zigbee stack (to be added)
- `esp_wifi` / `esp_http_server` — Wi-Fi connectivity and REST API (optional)
- `esp_https_ota` — Over-the-air updates

### Build Commands

**The only supported way to build and flash this project on Windows is the
`firmware/build_and_flash.ps1` script** (adapted from the SensorHUB project).
It activates the ESP-IDF environment itself — no manual environment setup is
required or allowed.

> **Rule for AI agents:** if `build_and_flash.ps1` fails, **stop immediately
> and report the failure to the user**. Do NOT look for workarounds: no manual
> `PATH`/`IDF_PATH` setup, no raw `idf.py` invocation with hand-crafted
> environment variables, no alternative toolchains. Show the error output and
> wait for the user's instructions.

Requires **ESP-IDF v6.0.2** installed. The project targets **ESP32-C6**.

### Script paths (auto-configured, overridable via parameters)

| Parameter | Default value |
|-----------|---------------|
| `-IdfPath` | `C:\esp\v6.0.2\esp-idf` |
| `-IdfToolsPath` | `C:\Espressif` |
| `-PythonEnvPath` | `C:\Espressif\tools\python\v6.0.2\venv` |
| `-Port` | `COM3` (USB Serial JTAG) |

### Usage

```powershell
# Build only
.\build_and_flash.ps1 -BuildOnly

# Clean build
.\build_and_flash.ps1 -BuildOnly -Clean

# Build and flash to COM3 (default port)
.\build_and_flash.ps1

# Build, flash, and open the serial monitor
.\build_and_flash.ps1 -Monitor
```

> **Note:** The preferred way is to run the script from a native PowerShell
> prompt as shown above. It can also be invoked from Git Bash / MSYS2 / MinGW
> or from agent shells via `powershell.exe`:
> ```bash
> powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\_Source\ZigbeeHUB\firmware\build_and_flash.ps1" -BuildOnly
> ```
> The script automatically strips the `MSYSTEM` environment variable from its
> process environment so ESP-IDF can activate.

### Linux / macOS (reference only)

The helper script is Windows-only. On other systems use the standard ESP-IDF
flow:

```bash
. $IDF_PATH/export.sh          # activate environment (run first)
idf.py set-target esp32c6      # once per project
idf.py build                   # build
idf.py -p /dev/ttyUSB0 flash   # flash
idf.py monitor                 # serial monitor
idf.py fullclean               # clean build artifacts
```

> **Important:** the target chip is flashed and controlled over the same
> **USB Serial JTAG on COM3** that the WebUI server uses for the JSON protocol.
> Stop the WebUI server before flashing, and restart it afterwards.

## Naming Conventions

### Firmware
- Use snake_case for files and functions
- Use UPPER_CASE for macros and constants
- Main file: `main.c` / `main.cpp`
- Module prefix: `zb_` (zigbee), `hub_`, `com_`

## Git Workflow

1. **Main branch**: `main` - stable releases only
2. **Develop branch**: `develop` - integration branch
3. **Feature branches**: `feature/{name}` - new features

## WebUI State Management

The WebUI uses a single authority for persisted device state.

- **Source of truth:** `Device.state` in the database.
- **Only valid writers:** `DeviceStateManager` (`app/services/device_state_manager.py`) updates `Device.state`.
- **Firmware protocol contract:**
  - `state_change` events carry actual attribute values and are the only events that update `Device.state`.
  - `*_ack` events (`on_ack`, `off_ack`, `read_attr_ack`, …) contain only `ok`/`error` and report whether the firmware accepted the command. They must **not** be used to update state.
  - `command_status` events report delivery/completion/timeout and may mark a device online on `delivered`/`completed`, but must **not** mark it offline on `timeout`/`failed` (liveness belongs to pings and `state_change`) and must **not** update `Device.state`.
- **Command lifecycle:** `HubService.send_command` registers each command in `DeviceStateManager`. The pending command is resolved when a matching `state_change` arrives or when `command_status` reports a terminal status; unresolved entries are reaped after a TTL (see `DeviceStateManager.sweep_expired`).
- **Automation:** graph node executors send commands through `HubService` and read state from the in-memory cache (`HubService.get_cached_devices()`). They never write to the database directly.
- **Frontend:** the UI reflects pending commands via `pendingCommands`, but it only mutates `device.state` on `state_change` events.

## Important Notes

- All documentation and code in **English**
- **Temporary scripts and WIP files go to `.agents/` only - not tracked in git**
- Datasheets are confidential - do not commit without checking licenses
- Manufacturing files are generated outputs - use releases for distribution
