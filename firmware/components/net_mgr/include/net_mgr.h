#pragma once

#include <stdbool.h>
#include "esp_err.h"
#include "esp_event.h"
#include "esp_http_server.h"

#ifdef __cplusplus
extern "C" {
#endif

ESP_EVENT_DECLARE_BASE(NET_MGR_EVENT);

#define NET_MGR_SSID_MAX_LEN 32
#define NET_MGR_PASS_MAX_LEN 64

typedef enum {
    NET_EVENT_WIFI_CONNECTED = 0,
    NET_EVENT_WIFI_DISCONNECTED,
    NET_EVENT_WIFI_PROVISION_DONE,
} net_mgr_event_t;

esp_err_t net_mgr_init(void);
esp_err_t net_mgr_start_provisioning(void);
esp_err_t net_mgr_connect(const char *ssid, const char *pass);
esp_err_t net_mgr_erase_credentials(void);
bool      net_mgr_is_connected(void);
esp_err_t net_mgr_get_ip(char *buf, size_t len);

/* Register the provisioning URI handler on an existing HTTP server.
 * Call this after httpd_start() and before the server starts accepting requests. */
esp_err_t net_mgr_register_provisioning_handler(httpd_handle_t server);

#ifdef __cplusplus
}
#endif
