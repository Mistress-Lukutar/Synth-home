#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define HTTP_API_KEY_LEN 64

esp_err_t http_api_init(void);
void      http_api_set_api_key(const char *api_key);

#ifdef __cplusplus
}
#endif
