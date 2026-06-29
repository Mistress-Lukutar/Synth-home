idf_component_register(
    SRCS "mdns_svc.c"
    INCLUDE_DIRS "include"
    REQUIRES "espressif__mdns" "hub_config"
)
