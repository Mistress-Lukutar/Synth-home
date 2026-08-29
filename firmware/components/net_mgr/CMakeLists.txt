idf_component_register(
    SRCS "net_mgr.c"
    INCLUDE_DIRS "include"
    REQUIRES "esp_wifi" "esp_event" "nvs_flash" "nvs_storage" "esp_netif" "esp_http_server" "cjson"
)
