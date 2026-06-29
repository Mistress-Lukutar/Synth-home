idf_component_register(
    SRCS "zb_stack.c"
    INCLUDE_DIRS "include"
    REQUIRES "espressif__esp-zigbee-lib" "espressif__esp-zboss-lib" "nvs_flash" "esp_event" "nvs_storage" "zb_cmd_tracker"
)
