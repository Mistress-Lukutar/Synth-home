idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES "nvs_storage" "hub_config" "com_pipeline" "zb_stack" "zb_device_mgr" "zb_clusters" "zb_cmd_tracker" "serial_api" "color_utils"
)
