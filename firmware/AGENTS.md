# AGENTS.md - ZigbeeHUB Firmware

## Project Overview

This is an **ESP-IDF 5.5.1** firmware project written in **C** that targets the **ESP32-C6**. It implements a **Zigbee Coordinator (ZC)** hub which forms and manages a Zigbee network, controls end-devices (On/Off, Level, Color clusters), and exposes both a USB Serial JSON interface and a Wi-Fi based HTTP/WebSocket API.

The project is located under `firmware/` and uses the standard ESP-IDF component-based build system with CMake.

### Key Configuration Files

| File | Purpose |
|------|---------|
| `CMakeLists.txt` | Root project CMake file (project name: `zigbee_hub`) |
| `sdkconfig.defaults` | Default SDKConfig overrides (Zigbee enabled, ZCZR role, custom partition table, 4 MB flash) |
| `sdkconfig` | Auto-generated full SDK configuration for ESP32-C6 |
| `partitions.csv` | Custom partition table: nvs, phy_init, factory app, zb_storage, zb_fct |
| `dependencies.lock` | Component manager lock file. Locks: `espressif/esp-zboss-lib` 1.6.4, `espressif/esp-zigbee-lib` 1.6.8, `espressif/mdns` 1.11.0, `idf` 5.5.1 |
| `main/idf_component.yml` | Component manifest declaring managed dependencies (`espressif/mdns`, `espressif/esp-zigbee-lib`, `espressif/esp-zboss-lib`) |
| `.clang-format` | Code formatting rules (LLVM-based, tabs, indent width 4) |
| `.clangd` | clangd LSP configuration |

## Technology Stack

- **Framework**: ESP-IDF 5.5.1
- **Target SoC**: ESP32-C6 (RISC-V)
- **Language**: C (C11/C17 compatible)
- **RTOS**: FreeRTOS (included in ESP-IDF)
- **Zigbee Stack**: Espressif `esp-zigbee-lib` + `esp-zboss-lib`
- **JSON**: `cJSON` (bundled with ESP-IDF)
- **Networking**: Wi-Fi STA/AP, `esp_http_server`, WebSocket support (`CONFIG_HTTPD_WS_SUPPORT=y`)
- **mDNS**: `espressif/mdns` for local service discovery
- **Storage**: NVS flash for persistent settings and device tables

## Directory Layout

```
firmware/
├── CMakeLists.txt
├── sdkconfig
├── sdkconfig.defaults
├── partitions.csv
├── dependencies.lock
├── main/
│   ├── CMakeLists.txt
│   ├── idf_component.yml
│   └── main.c                  # Application entry point (app_main)
├── components/                 # Custom IDF components
│   ├── com_pipeline/           # Internal pub/sub event bus
│   ├── http_api/               # REST HTTP API server (port 80)
│   ├── mdns_svc/               # mDNS service advertisement
│   ├── net_mgr/                # Wi-Fi network manager (STA/AP + provisioning)
│   ├── nvs_storage/            # NVS abstraction layer
│   ├── serial_api/             # USB Serial JSON command interface
│   ├── ws_server/              # WebSocket server (port 81)
│   ├── zb_clusters/            # ZCL cluster command wrappers
│   ├── zb_device_mgr/          # Zigbee device table + interview logic
│   └── zb_stack/               # Zigbee stack init, network formation, callbacks
└── managed_components/         # Auto-downloaded components
    ├── espressif__esp-zboss-lib/
    ├── espressif__esp-zigbee-lib/
    └── espressif__mdns/
```

## Component Architecture

### Communication Flow

1. `main.c` initializes all components in order: `nvs_storage` -> `esp_event` -> `com_pipeline` -> `zb_stack` -> `zb_device_mgr` -> `serial_api`.
2. `zb_stack` runs the Zigbee stack in a dedicated FreeRTOS task. It handles network formation/steering, device join/leave signals, attribute reports, and read-attribute responses.
3. `zb_device_mgr` maintains an in-memory device table (max 32 devices) persisted to NVS. When a device joins, it performs an "interview" (Active EP request -> Simple Descriptor request -> reads ColorCapabilities) to discover endpoints and color capabilities.
4. `com_pipeline` is a thread-safe pub/sub event bus backed by a FreeRTOS queue. It serializes events to JSON and broadcasts them via `ws_server`.
5. `serial_api` reads line-delimited JSON commands from `stdin` (USB Serial) and dispatches them to `zb_clusters`. It also subscribes to `com_pipeline` to echo events back over stdout.
6. `http_api` provides a REST API on port 80 (`/health`, `/devices`, `/devices/{ieee}/...`, `/network/permit-join`). It uses `X-API-Key` header authentication.
7. `ws_server` runs a WebSocket server on port 81 (`/ws`) with ping/pong keep-alive. It requires the `X-API-Key` header on handshake. Only one client is allowed at a time.
8. `net_mgr` manages Wi-Fi. On boot it attempts STA mode with saved credentials. If none exist, it starts an open AP (`ZigbeeHUB-XXXX`) with a captive provisioning endpoint (`POST /provision/wifi`). After max reconnect attempts it falls back to provisioning.
9. `nvs_storage` wraps `nvs_flash` with typed helpers (`set_blob`, `get_u8`, `set_str`, etc.).
10. `mdns_svc` advertises `_http._tcp` on port 80 with `hub_id` and `firmware` TXT records.

### Component Dependency Graph (simplified)

```
main
├── nvs_storage
├── com_pipeline
│   └── ws_server
├── zb_stack
│   └── nvs_storage
├── zb_device_mgr
│   ├── nvs_storage
│   ├── zb_stack
│   └── com_pipeline
├── zb_clusters
│   ├── zb_device_mgr
│   ├── zb_stack
│   └── com_pipeline
└── serial_api
    ├── zb_device_mgr
    ├── zb_clusters
    ├── zb_stack
    └── com_pipeline

net_mgr
├── nvs_storage
└── esp_http_server (provisioning captive portal)

http_api
├── net_mgr
├── zb_device_mgr
├── zb_clusters
├── com_pipeline
└── esp_http_server

ws_server
└── com_pipeline

mdns_svc
└── espressif__mdns
```

## Naming Conventions

- **Files and functions**: `snake_case`
- **Macros and constants**: `UPPER_CASE`
- **Module prefixes**:
  - `zb_` — Zigbee-related (`zb_stack`, `zb_device_mgr`, `zb_clusters`)
  - `com_` — Communication/event pipeline (`com_pipeline`)
  - `net_` — Network manager (`net_mgr`)
  - `nvs_` — NVS storage (`nvs_storage`)
  - `ws_` — WebSocket server (`ws_server`)
  - `http_` — HTTP API (`http_api`)
  - `mdns_` — mDNS service (`mdns_svc`)
  - `serial_` — Serial API (`serial_api`)
- **Static file-scope variables**: `s_` prefix (e.g., `s_mutex`)
- **Tags for ESP_LOG**: lowercase module name with underscore (e.g., `"zb_stack"`, `"com_pipeline"`)
- **Headers**: use `#pragma once` and `extern "C" { }` guards
- **Comments and documentation**: English only

## Code Style Guidelines

The repository includes a `.clang-format` file:
- Based on LLVM style
- Use tabs (not spaces)
- Indent width: 4
- Tab width: 4

Run formatting before committing:
```bash
clang-format -i components/*/*.c components/*/*.h main/*.c
```

## Build and Test Commands

### Prerequisites
- ESP-IDF 5.5.1 installed
- Target set to `esp32c6`

### Linux / macOS
```bash
cd firmware
idf.py set-target esp32c6
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

### Windows (PowerShell with ESP-IDE)
```powershell
$env:IDF_PATH = "C:\Espressif\frameworks\esp-idf-v5.5.1"
$env:IDF_PYTHON_ENV_PATH = "C:\Espressif\python_env\idf5.5_py3.11_env"
$env:ESP_ROM_ELF_DIR = "C:\Espressif\tools\esp-rom-elfs\20241011"
$env:PATH = "C:\Espressif\python_env\idf5.5_py3.11_env\Scripts;" +
            "C:\Espressif\tools\riscv32-esp-elf\esp-14.2.0_20241119\riscv32-esp-elf\bin;" +
            "C:\Espressif\tools\cmake\3.30.2\bin;" +
            "C:\Espressif\tools\ninja\1.12.1;" +
            "C:\Espressif\frameworks\esp-idf-v5.5.1\tools;" +
            $env:PATH

cd C:\_Source\ZigbeeHUB\firmware
python C:\Espressif\frameworks\esp-idf-v5.5.1\tools\idf.py set-target esp32c6
python C:\Espressif\frameworks\esp-idf-v5.5.1\tools\idf.py build
```

### Flash Directly (esptool)
```bash
python -m esptool --chip esp32c6 -b 460800 --before default_reset --after hard_reset write_flash --flash_mode dio --flash_size 4MB --flash_freq 80m 0x0 build/bootloader/bootloader.bin 0x8000 build/partition_table/partition-table.bin 0x10000 build/zigbee_hub.bin
```

### Adding a New Component

Create a directory under `firmware/components/<name>/`:

```
components/<name>/
├── CMakeLists.txt
├── Kconfig                 # (optional)
├── include/
│   └── <name>.h
└── <name>.c
```

**CMakeLists.txt template:**
```cmake
idf_component_register(
    SRCS "<name>.c"
    INCLUDE_DIRS "include"
    REQUIRES "esp_event" "nvs_flash"
    PRIV_REQUIRES "driver"
)
```

**Register in `main/CMakeLists.txt`:**
```cmake
idf_component_register(
    SRCS main.c
    REQUIRES "my_component"
)
```

## Testing Strategy

- **No unit tests or integration tests currently exist** for custom components in this repository.
- The `managed_components/` contain upstream tests but these are not part of the project test suite.
- Testing is currently done manually via:
  1. USB Serial JSON commands (e.g., `{"cmd":"list"}`, `{"cmd":"on","ieee":"0x..."}`)
  2. HTTP REST calls to the device endpoints
  3. WebSocket client connection for real-time event streaming
  4. Physical Zigbee end-device pairing and command verification

If adding automated tests, consider using ESP-IDF's `unity` test framework and placing tests under `test/` directories inside components.

## Runtime Architecture Details

### Zigbee Network
- **Role**: Coordinator (`ESP_ZB_DEVICE_TYPE_COORDINATOR`)
- **Endpoint**: 1 (used to originate ZCL traffic)
- **Default PAN ID**: `0x1A62`
- **Default Channel**: 11
- **Max children**: 10
- **Network key**: randomly generated on first boot, persisted to NVS
- **Commissioning**: BDB top-level commissioning (formation -> steering). On reboot, network params are restored from NVS.

### Device Interview Process
When a device joins:
1. `zb_stack` detects `ESP_ZB_ZDO_SIGNAL_DEVICE_ANNCE` -> calls `on_device_join`
2. `main.c` adds device to `zb_device_mgr` and starts interview
3. `zb_device_mgr` sends `Active_EP_req`
4. For each endpoint, sends `Simple_Desc_req`
5. If endpoint has cluster `0x0300` (Color Control), reads attributes `0x4002` (ColorCapabilities) and `0x0008` (ColorMode)
6. Capabilities (`hs`, `xy`, `ct`, `color_loop`) are persisted with the device record

### Serial API Protocol
The firmware communicates over USB Serial (UART / USB-Serial-JTAG) using newline-delimited JSON.

**Input commands (examples):**
```json
{"cmd":"list"}
{"cmd":"on","ieee":"0x0123456789ABCDEF"}
{"cmd":"off","ieee":"0x0123456789ABCDEF"}
{"cmd":"toggle","ieee":"0x0123456789ABCDEF"}
{"cmd":"level","ieee":"0x...","level":128}
{"cmd":"color","ieee":"0x...","hex":"#FF00AA"}
{"cmd":"permit","duration":60}
```

**Output events:**
```json
{"type":"device_joined","ieee":"0x...","network_addr":"0x...","device_type":"end_device","power_source":"mains"}
{"type":"state_change","ieee":"0x...","changes":[{"cluster":"0x0006","attribute":"0x0000","value":true}]}
{"type":"device_left","ieee":"0x...","reason":"left"}
```

### HTTP API Endpoints
All endpoints require `X-API-Key` header.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Hub status + network + uptime |
| GET | `/devices` | List all known devices |
| GET | `/devices/{ieee}` | Get single device details |
| GET | `/devices/{ieee}/color-capabilities` | Get color caps |
| POST | `/devices/{ieee}/on` | Send On command |
| POST | `/devices/{ieee}/off` | Send Off command |
| POST | `/devices/{ieee}/toggle` | Send Toggle command |
| POST | `/devices/{ieee}/level` | Body: `{"level":128,"transition":1.0}` |
| POST | `/devices/{ieee}/color` | Body: `{"hex":"#FF00AA","transition":1.0}` or `{"mode":"hs","hue":128,"saturation":200,"transition":1.0}` |
| POST | `/network/permit-join` | Body: `{"duration":60}` |

All POST commands return `202 Accepted` with a `correlation_id`.

### WebSocket
- Endpoint: `ws://<hub-ip>:81/ws`
- Requires `X-API-Key` header during handshake
- Sends ping every 30 seconds; expects pong within 5 seconds or connection is closed
- Broadcasts all `com_pipeline` events as JSON text frames

### Wi-Fi Provisioning
- If no saved credentials: AP `ZigbeeHUB-XXXX` (open) is started
- Provisioning endpoint: `POST http://192.168.4.1/provision/wifi` with JSON body `{"ssid":"...","password":"..."}`
- After provisioning, hub switches to STA mode and connects
- On disconnect, auto-reconnect up to 3 times, then falls back to AP provisioning mode

## Security Considerations

- **API Key**: Both HTTP and WebSocket APIs use a shared `X-API-Key` header for basic authentication. The key is set at runtime (not compiled in).
- **Wi-Fi Provisioning AP**: The provisioning access point is **open** (`WIFI_AUTH_OPEN`). Any nearby device can connect and send credentials.
- **Zigbee Network Key**: Generated randomly on first boot and persisted to NVS. Network is not using install codes (`install_code_policy = false`).
- **No TLS/HTTPS**: The HTTP server runs on plain HTTP (port 80). WebSocket is unencrypted (port 81).
- **No OTA implementation**: Although `esp_https_ota` is mentioned as a key component, no OTA logic is currently present in the custom source code.

## Git Workflow

1. **Main branch**: `main` — stable releases only
2. **Develop branch**: `develop` — integration branch
3. **Feature branches**: `feature/{name}` — new features

## Important Notes

- All documentation and code in **English**
- **Temporary scripts and WIP files go to `.agents/` only — not tracked in git**
- Datasheets are confidential — do not commit without checking licenses
- Manufacturing files are generated outputs — use releases for distribution
