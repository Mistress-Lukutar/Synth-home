#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t mdns_svc_init(const char *hub_id);
const char *mdns_svc_get_hostname(void);

#ifdef __cplusplus
}
#endif
