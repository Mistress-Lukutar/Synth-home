#include "mdns_svc.h"
#include "mdns.h"
#include "esp_log.h"
#include "hub_config.h"
#include <stdio.h>
#include <string.h>

static const char *TAG = "mdns_svc";

#define MDNS_HOSTNAME_PREFIX "zigbee-hub-"
#define MDNS_HOSTNAME_MAX_LEN 64

static char mdns_hostname[MDNS_HOSTNAME_MAX_LEN] = {0};

esp_err_t mdns_svc_init(const char *hub_id)
{
    if (hub_id == NULL) {
        ESP_LOGE(TAG, "hub_id is NULL");
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t err = mdns_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "mDNS init failed: %s", esp_err_to_name(err));
        return err;
    }

    int ret = snprintf(mdns_hostname, sizeof(mdns_hostname), "%s%s",
                       MDNS_HOSTNAME_PREFIX, hub_id);
    if (ret < 0 || ret >= (int)sizeof(mdns_hostname)) {
        ESP_LOGE(TAG, "Hostname buffer too small");
        return ESP_ERR_INVALID_SIZE;
    }

    err = mdns_hostname_set(mdns_hostname);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "mDNS hostname set failed: %s", esp_err_to_name(err));
        return err;
    }

    const char *fw_ver = hub_config_get_fw_version();
    mdns_txt_item_t txt_items[] = {
        {"hub_id", hub_id},
        {"firmware", fw_ver ? fw_ver : "unknown"},
    };

    err = mdns_service_add(NULL, "_http", "_tcp", 80, txt_items,
                           sizeof(txt_items) / sizeof(txt_items[0]));
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "mDNS service add failed: %s", esp_err_to_name(err));
        return err;
    }

    return ESP_OK;
}

const char *mdns_svc_get_hostname(void)
{
    return mdns_hostname;
}
