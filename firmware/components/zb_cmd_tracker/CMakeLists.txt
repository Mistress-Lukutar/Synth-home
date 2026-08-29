idf_component_register(
    SRCS "zb_cmd_tracker.c"
    INCLUDE_DIRS "include"
    REQUIRES "com_pipeline" "esp_timer"
    PRIV_REQUIRES "espressif__esp-zigbee-lib"
)

# esp-zigbee-lib 2.x compat headers (CONFIG_ZB_SDK_1xx) emit #warning
# "deprecated" banners; keep them from breaking -Werror builds.
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error=cpp)
