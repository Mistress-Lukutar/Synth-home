#pragma once

#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t nvs_storage_init(void);

esp_err_t nvs_storage_set_blob(const char *ns, const char *key, const void *data, size_t len);
esp_err_t nvs_storage_get_blob(const char *ns, const char *key, void *out, size_t *len);

esp_err_t nvs_storage_set_str(const char *ns, const char *key, const char *str);
esp_err_t nvs_storage_get_str(const char *ns, const char *key, char *out, size_t *len);

esp_err_t nvs_storage_set_u8(const char *ns, const char *key, uint8_t value);
esp_err_t nvs_storage_get_u8(const char *ns, const char *key, uint8_t *out);

esp_err_t nvs_storage_set_u16(const char *ns, const char *key, uint16_t value);
esp_err_t nvs_storage_get_u16(const char *ns, const char *key, uint16_t *out);

esp_err_t nvs_storage_set_u32(const char *ns, const char *key, uint32_t value);
esp_err_t nvs_storage_get_u32(const char *ns, const char *key, uint32_t *out);

esp_err_t nvs_storage_set_u64(const char *ns, const char *key, uint64_t value);
esp_err_t nvs_storage_get_u64(const char *ns, const char *key, uint64_t *out);

esp_err_t nvs_storage_erase(const char *ns, const char *key);
esp_err_t nvs_storage_erase_namespace(const char *ns);

#ifdef __cplusplus
}
#endif
