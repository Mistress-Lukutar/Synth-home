idf_component_register(
    SRCS "http_api.c"
    INCLUDE_DIRS "include"
    REQUIRES "esp_http_server" "cjson" "nvs_storage" "zb_device_mgr" "zb_clusters" "zb_stack" "com_pipeline" "net_mgr" "esp_timer" "color_utils"
)
