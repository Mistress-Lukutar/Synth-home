#include "hub_config.h"

#include <string.h>
#include "esp_log.h"
#include "nvs_storage.h"
#include "esp_mac.h"

static const char *TAG = "hub_config";

#define HUB_CFG_NS          "hub_cfg"
#define HUB_CFG_KEY_API     "api_key"
#define HUB_CFG_KEY_FW      "fw_ver"
#define HUB_CFG_KEY_ID      "hub_id"

static char s_api_key[HUB_CONFIG_API_KEY_LEN] = {0};
static char s_fw_ver[HUB_CONFIG_FW_VER_LEN]  = "1.0.0";
static char s_hub_id[HUB_CONFIG_HUB_ID_LEN]  = {0};

static esp_err_t s_load_str(const char *key, char *buf, size_t buf_len)
{
	size_t len = buf_len;
	esp_err_t err = nvs_storage_get_str(HUB_CFG_NS, key, buf, &len);
	if (err == ESP_ERR_NOT_FOUND) {
		return ESP_OK; /* keep default */
	}
	return err;
}

esp_err_t hub_config_init(void)
{
	s_load_str(HUB_CFG_KEY_API, s_api_key, sizeof(s_api_key));
	s_load_str(HUB_CFG_KEY_FW, s_fw_ver, sizeof(s_fw_ver));
	s_load_str(HUB_CFG_KEY_ID, s_hub_id, sizeof(s_hub_id));

	if (s_hub_id[0] == '\0') {
		uint8_t mac[6];
		if (esp_read_mac(mac, ESP_MAC_WIFI_STA) == ESP_OK) {
			snprintf(s_hub_id, sizeof(s_hub_id), "%02X%02X%02X%02X",
				 mac[2], mac[3], mac[4], mac[5]);
		} else {
			strncpy(s_hub_id, "UNKNOWN", sizeof(s_hub_id) - 1);
		}
		s_hub_id[sizeof(s_hub_id) - 1] = '\0';
	}

	ESP_LOGI(TAG, "Initialized (hub_id=%s, fw=%s)", s_hub_id, s_fw_ver);
	return ESP_OK;
}

const char *hub_config_get_api_key(void)
{
	return s_api_key;
}

esp_err_t hub_config_set_api_key(const char *api_key)
{
	if (api_key == NULL) {
		return ESP_ERR_INVALID_ARG;
	}
	strncpy(s_api_key, api_key, sizeof(s_api_key) - 1);
	s_api_key[sizeof(s_api_key) - 1] = '\0';
	return nvs_storage_set_str(HUB_CFG_NS, HUB_CFG_KEY_API, s_api_key);
}

const char *hub_config_get_fw_version(void)
{
	return s_fw_ver;
}

esp_err_t hub_config_set_fw_version(const char *version)
{
	if (version == NULL) {
		return ESP_ERR_INVALID_ARG;
	}
	strncpy(s_fw_ver, version, sizeof(s_fw_ver) - 1);
	s_fw_ver[sizeof(s_fw_ver) - 1] = '\0';
	return nvs_storage_set_str(HUB_CFG_NS, HUB_CFG_KEY_FW, s_fw_ver);
}

const char *hub_config_get_hub_id(void)
{
	return s_hub_id;
}

esp_err_t hub_config_set_hub_id(const char *hub_id)
{
	if (hub_id == NULL) {
		return ESP_ERR_INVALID_ARG;
	}
	strncpy(s_hub_id, hub_id, sizeof(s_hub_id) - 1);
	s_hub_id[sizeof(s_hub_id) - 1] = '\0';
	return nvs_storage_set_str(HUB_CFG_NS, HUB_CFG_KEY_ID, s_hub_id);
}
