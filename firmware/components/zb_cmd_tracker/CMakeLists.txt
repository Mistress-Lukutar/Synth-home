idf_component_register(
    SRCS "zb_cmd_tracker.c"
    INCLUDE_DIRS "include"
    REQUIRES "com_pipeline" "esp_timer"
    PRIV_REQUIRES "espressif__esp-zigbee-lib"
)
