# AGENTS.md - ZigbeeHUB

## Firmware Project Details

The firmware is an **ESP-IDF 5.5.1** project targeting **ESP32-C6**.

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

#### Linux/macOS (Standard)
```bash
cd firmware
idf.py set-target esp32c6
idf.py build
idf.py flash monitor
```

#### Windows (ESP-IDF 5.5.1 with ESP-IDE)
When using ESP-IDF installed via ESP-IDE without the full environment setup, use PowerShell with explicit environment variables:

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

**Required Environment Variables:**
| Variable | Typical Value |
|----------|---------------|
| `IDF_PATH` | `C:\Espressif\frameworks\esp-idf-v5.5.1` |
| `IDF_PYTHON_ENV_PATH` | `C:\Espressif\python_env\idf5.5_py3.11_env` |
| `ESP_ROM_ELF_DIR` | `C:\Espressif\tools\esp-rom-elfs\20241011` |

#### Flash Commands
```bash
# Standard flash (run from firmware/ directory)
idf.py -p PORT flash

# Or using esptool directly
python -m esptool --chip esp32c6 -b 460800 --before default_reset --after hard_reset write_flash --flash_mode dio --flash_size 4MB --flash_freq 80m 0x0 build/bootloader/bootloader.bin 0x8000 build/partition_table/partition-table.bin 0x10000 build/zigbee_hub.bin
```

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

## Important Notes

- All documentation and code in **English**
- **Temporary scripts and WIP files go to `.agents/` only - not tracked in git**
- Datasheets are confidential - do not commit without checking licenses
- Manufacturing files are generated outputs - use releases for distribution
