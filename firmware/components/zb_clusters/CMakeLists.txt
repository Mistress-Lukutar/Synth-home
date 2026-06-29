idf_component_register(
    SRCS "zb_clusters.c"
    INCLUDE_DIRS "include"
    REQUIRES "zb_device_mgr" "zb_stack" "com_pipeline" "zb_cmd_tracker"
)
