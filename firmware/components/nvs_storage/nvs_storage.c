#include "nvs_storage.h"
#include "nvs_flash.h"
#include "esp_log.h"

static const char *TAG = "nvs_storage";

esp_err_t nvs_storage_init(void)
{
    return nvs_flash_init();
}

esp_err_t nvs_storage_set_blob(const char *ns, const char *key, const void *data, size_t len)
{
    if (ns == NULL || key == NULL || data == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_set_blob(handle, key, data, len);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    } else if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_set_blob failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_get_blob(const char *ns, const char *key, void *out, size_t *len)
{
    if (ns == NULL || key == NULL || len == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_get_blob(handle, key, out, len);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = ESP_ERR_NOT_FOUND;
    } else if (err != ESP_OK && err != ESP_ERR_NVS_INVALID_LENGTH) {
        ESP_LOGE(TAG, "nvs_get_blob failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_set_str(const char *ns, const char *key, const char *str)
{
    if (ns == NULL || key == NULL || str == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_set_str(handle, key, str);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    } else if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_set_str failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_get_str(const char *ns, const char *key, char *out, size_t *len)
{
    if (ns == NULL || key == NULL || len == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_get_str(handle, key, out, len);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = ESP_ERR_NOT_FOUND;
    } else if (err != ESP_OK && err != ESP_ERR_NVS_INVALID_LENGTH) {
        ESP_LOGE(TAG, "nvs_get_str failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_set_u8(const char *ns, const char *key, uint8_t value)
{
    if (ns == NULL || key == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_set_u8(handle, key, value);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    } else if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_set_u8 failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_get_u8(const char *ns, const char *key, uint8_t *out)
{
    if (ns == NULL || key == NULL || out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_get_u8(handle, key, out);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = ESP_ERR_NOT_FOUND;
    } else if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_get_u8 failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_set_u16(const char *ns, const char *key, uint16_t value)
{
    if (ns == NULL || key == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_set_u16(handle, key, value);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    } else if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_set_u16 failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_get_u16(const char *ns, const char *key, uint16_t *out)
{
    if (ns == NULL || key == NULL || out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_get_u16(handle, key, out);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = ESP_ERR_NOT_FOUND;
    } else if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_get_u16 failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_set_u32(const char *ns, const char *key, uint32_t value)
{
    if (ns == NULL || key == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_set_u32(handle, key, value);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    } else if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_set_u32 failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_get_u32(const char *ns, const char *key, uint32_t *out)
{
    if (ns == NULL || key == NULL || out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_get_u32(handle, key, out);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = ESP_ERR_NOT_FOUND;
    } else if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_get_u32 failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_set_u64(const char *ns, const char *key, uint64_t value)
{
    if (ns == NULL || key == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_set_u64(handle, key, value);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    } else if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_set_u64 failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_get_u64(const char *ns, const char *key, uint64_t *out)
{
    if (ns == NULL || key == NULL || out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_get_u64(handle, key, out);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = ESP_ERR_NOT_FOUND;
    } else if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_get_u64 failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_erase(const char *ns, const char *key)
{
    if (ns == NULL || key == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_erase_key(handle, key);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    } else if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = ESP_ERR_NOT_FOUND;
    } else {
        ESP_LOGE(TAG, "nvs_erase_key failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}

esp_err_t nvs_storage_erase_namespace(const char *ns)
{
    if (ns == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(ns, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }

    err = nvs_erase_all(handle);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    } else {
        ESP_LOGE(TAG, "nvs_erase_all failed: %s", esp_err_to_name(err));
    }

    nvs_close(handle);
    return err;
}
