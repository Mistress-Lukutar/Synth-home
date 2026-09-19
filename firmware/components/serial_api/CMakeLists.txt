idf_component_register(
    SRCS "serial_api.c"
    INCLUDE_DIRS "include"
    REQUIRES "zb_device_mgr" "hub_stats" "esp_driver_usb_serial_jtag" "zb_clusters" "zb_stack" "com_pipeline" "cjson" "color_utils"
)
