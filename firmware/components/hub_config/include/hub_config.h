#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define HUB_CONFIG_API_KEY_LEN   64
#define HUB_CONFIG_FW_VER_LEN    16
#define HUB_CONFIG_HUB_ID_LEN    32

esp_err_t hub_config_init(void);

const char *hub_config_get_api_key(void);
esp_err_t   hub_config_set_api_key(const char *api_key);

const char *hub_config_get_fw_version(void);
esp_err_t   hub_config_set_fw_version(const char *version);

const char *hub_config_get_hub_id(void);
esp_err_t   hub_config_set_hub_id(const char *hub_id);

#ifdef __cplusplus
}
#endif
