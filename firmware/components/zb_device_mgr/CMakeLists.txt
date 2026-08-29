idf_component_register(
    SRCS "zb_device_mgr.c"
    INCLUDE_DIRS "include"
    REQUIRES "nvs_storage" "zb_stack" "com_pipeline" "espressif__esp-zigbee-lib"
    PRIV_REQUIRES "zb_clusters"
)

# esp-zigbee-lib 2.x compat headers (CONFIG_ZB_SDK_1xx) emit #warning
# "deprecated" banners; keep them from breaking -Werror builds.
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error=cpp)
