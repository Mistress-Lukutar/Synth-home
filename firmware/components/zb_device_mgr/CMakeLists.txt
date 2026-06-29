idf_component_register(
    SRCS "zb_device_mgr.c"
    INCLUDE_DIRS "include"
    REQUIRES "nvs_storage" "zb_stack" "com_pipeline" "espressif__esp-zigbee-lib"
    PRIV_REQUIRES "zb_clusters"
)
