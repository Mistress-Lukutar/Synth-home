#pragma once

#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define WS_API_KEY_LEN 64

esp_err_t ws_server_init(void);
esp_err_t ws_server_broadcast(const char *json_payload);
bool      ws_server_is_client_connected(void);
void      ws_server_set_api_key(const char *api_key);

#ifdef __cplusplus
}
#endif
