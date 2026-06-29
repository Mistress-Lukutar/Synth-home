idf_component_register(
    SRCS "serial_api.c"
    INCLUDE_DIRS "include"
    REQUIRES "zb_device_mgr" "zb_clusters" "zb_stack" "com_pipeline" "json" "color_utils"
)
