idf_component_register(
    SRCS "zb_stack.c"
    INCLUDE_DIRS "include"
    REQUIRES "espressif__esp-zigbee-lib" "espressif__esp-zboss-lib" "nvs_flash" "esp_event" "nvs_storage" "zb_cmd_tracker"
)

# esp-zigbee-lib 2.x compat headers (CONFIG_ZB_SDK_1xx) emit #warning
# "deprecated" banners; keep them from breaking -Werror builds.
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error=cpp)
