#include "net_mgr.h"
#include <string.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "nvs_storage.h"
#include "lwip/ip4_addr.h"
#include "cJSON.h"

#define NET_MGR_TAG                 "net_mgr"
#define NET_MGR_WIFI_CFG_NS         "wifi_cfg"
#define NET_MGR_WIFI_SSID_KEY       "ssid"
#define NET_MGR_WIFI_PASS_KEY       "pass"
#define NET_MGR_EVT_TIMEOUT_MS      1000
#define NET_MGR_MAX_RECONNECT_ATTEMPTS 3

ESP_EVENT_DECLARE_BASE(NET_MGR_EVENT);
ESP_EVENT_DEFINE_BASE(NET_MGR_EVENT);

static esp_netif_t    *s_sta_netif = NULL;
static esp_netif_t    *s_ap_netif  = NULL;
static bool            s_connected = false;
static char            s_ip_str[16] = {0};
static SemaphoreHandle_t s_mutex   = NULL;
static uint8_t         s_reconnect_attempts = 0;

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

static esp_err_t net_mgr_save_credentials(const char *ssid, const char *pass)
{
	esp_err_t err = nvs_storage_set_str(NET_MGR_WIFI_CFG_NS, NET_MGR_WIFI_SSID_KEY, ssid);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to save SSID: %s", esp_err_to_name(err));
		return err;
	}
	err = nvs_storage_set_str(NET_MGR_WIFI_CFG_NS, NET_MGR_WIFI_PASS_KEY, pass);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to save password: %s", esp_err_to_name(err));
		return err;
	}
	return ESP_OK;
}

static esp_err_t net_mgr_load_credentials(char *ssid, size_t *ssid_len,
                                          char *pass, size_t *pass_len)
{
	esp_err_t err = nvs_storage_get_str(NET_MGR_WIFI_CFG_NS, NET_MGR_WIFI_SSID_KEY,
					    ssid, ssid_len);
	if (err != ESP_OK) {
		return err;
	}
	err = nvs_storage_get_str(NET_MGR_WIFI_CFG_NS, NET_MGR_WIFI_PASS_KEY,
				  pass, pass_len);
	if (err != ESP_OK) {
		return err;
	}
	return ESP_OK;
}

static void net_mgr_set_connected(bool connected, const char *ip)
{
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	s_connected = connected;
	if (ip) {
		strncpy(s_ip_str, ip, sizeof(s_ip_str) - 1);
		s_ip_str[sizeof(s_ip_str) - 1] = '\0';
	} else {
		s_ip_str[0] = '\0';
	}
	xSemaphoreGive(s_mutex);
}

/* -------------------------------------------------------------------------- */
/* HTTP server handler                                                        */
/* -------------------------------------------------------------------------- */

static esp_err_t provision_post_handler(httpd_req_t *req)
{
	char buf[256];
	int ret, remaining = req->content_len;

	if (remaining <= 0 || remaining >= (int)sizeof(buf)) {
		httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid content length");
		return ESP_FAIL;
	}

	ret = httpd_req_recv(req, buf, remaining);
	if (ret <= 0) {
		if (ret == HTTPD_SOCK_ERR_TIMEOUT) {
			httpd_resp_send_408(req);
		}
		return ESP_FAIL;
	}
	buf[ret] = '\0';

	cJSON *root = cJSON_Parse(buf);
	if (root == NULL) {
		httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid JSON");
		return ESP_FAIL;
	}

	cJSON *ssid_item = cJSON_GetObjectItem(root, "ssid");
	cJSON *pass_item = cJSON_GetObjectItem(root, "password");
	if (!cJSON_IsString(ssid_item) || !cJSON_IsString(pass_item)) {
		cJSON_Delete(root);
		httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing ssid or password");
		return ESP_FAIL;
	}

	const char *ssid = ssid_item->valuestring;
	const char *pass = pass_item->valuestring;

	if (strlen(ssid) == 0) {
		cJSON_Delete(root);
		httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "SSID empty");
		return ESP_FAIL;
	}

	ESP_LOGI(NET_MGR_TAG, "Provisioning received SSID: %s", ssid);

	esp_err_t err = net_mgr_save_credentials(ssid, pass);
	cJSON_Delete(root);

	if (err != ESP_OK) {
		httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
				    "Failed to save credentials");
		return ESP_FAIL;
	}

	httpd_resp_set_type(req, "application/json");
	httpd_resp_sendstr(req, "{\"status\":\"ok\"}");

	esp_event_post(NET_MGR_EVENT, NET_EVENT_WIFI_PROVISION_DONE,
		       NULL, 0, pdMS_TO_TICKS(NET_MGR_EVT_TIMEOUT_MS));

	return ESP_OK;
}

static const httpd_uri_t provision_uri = {
	.uri       = "/provision/wifi",
	.method    = HTTP_POST,
	.handler   = provision_post_handler,
	.user_ctx  = NULL
};

/* -------------------------------------------------------------------------- */
/* Wi-Fi event handler                                                        */
/* -------------------------------------------------------------------------- */

static void net_mgr_internal_event_handler(void *arg, esp_event_base_t event_base,
                                           int32_t event_id, void *event_data)
{
	(void)arg;
	(void)event_data;

	if (event_base == NET_MGR_EVENT && event_id == NET_EVENT_WIFI_PROVISION_DONE) {
		char ssid[NET_MGR_SSID_MAX_LEN + 1] = {0};
		char pass[NET_MGR_PASS_MAX_LEN + 1] = {0};
		size_t ssid_len = sizeof(ssid);
		size_t pass_len = sizeof(pass);
		if (net_mgr_load_credentials(ssid, &ssid_len, pass, &pass_len) == ESP_OK) {
			net_mgr_connect(ssid, pass);
		}
	}
}

static void net_mgr_wifi_event_handler(void *arg, esp_event_base_t event_base,
                                       int32_t event_id, void *event_data)
{
	(void)arg;
	(void)event_data;

	if (event_base == WIFI_EVENT) {
		if (event_id == WIFI_EVENT_STA_START) {
			ESP_LOGI(NET_MGR_TAG, "STA started");
		} else if (event_id == WIFI_EVENT_STA_DISCONNECTED) {
			ESP_LOGW(NET_MGR_TAG, "STA disconnected (attempt %d/%d)",
				 s_reconnect_attempts + 1, NET_MGR_MAX_RECONNECT_ATTEMPTS);
			net_mgr_set_connected(false, NULL);
			esp_event_post(NET_MGR_EVENT, NET_EVENT_WIFI_DISCONNECTED,
				       NULL, 0, pdMS_TO_TICKS(NET_MGR_EVT_TIMEOUT_MS));
			s_reconnect_attempts++;
			if (s_reconnect_attempts < NET_MGR_MAX_RECONNECT_ATTEMPTS) {
				ESP_LOGI(NET_MGR_TAG, "Retrying connection...");
				vTaskDelay(pdMS_TO_TICKS(1000 * (1 << s_reconnect_attempts)));
				esp_wifi_connect();
			} else {
				ESP_LOGW(NET_MGR_TAG,
					 "Max reconnect attempts reached, falling back to provisioning");
				net_mgr_erase_credentials();
				net_mgr_start_provisioning();
			}
		} else if (event_id == WIFI_EVENT_AP_STACONNECTED) {
			ESP_LOGI(NET_MGR_TAG, "AP: station connected");
		} else if (event_id == WIFI_EVENT_AP_STADISCONNECTED) {
			ESP_LOGI(NET_MGR_TAG, "AP: station disconnected");
		}
	} else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
		ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
		char ip_str[16];
		esp_ip4addr_ntoa(&event->ip_info.ip, ip_str, sizeof(ip_str));
		ESP_LOGI(NET_MGR_TAG, "Got IP: %s", ip_str);
		s_reconnect_attempts = 0;
		net_mgr_set_connected(true, ip_str);
		esp_wifi_set_ps(WIFI_PS_NONE);
		ESP_LOGI(NET_MGR_TAG, "Wi-Fi power save disabled");
		esp_event_post(NET_MGR_EVENT, NET_EVENT_WIFI_CONNECTED,
			       NULL, 0, pdMS_TO_TICKS(NET_MGR_EVT_TIMEOUT_MS));
	}
}

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

esp_err_t net_mgr_init(void)
{
	s_mutex = xSemaphoreCreateMutex();
	if (!s_mutex) {
		ESP_LOGE(NET_MGR_TAG, "Failed to create mutex");
		return ESP_ERR_NO_MEM;
	}

	esp_err_t err = esp_netif_init();
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "esp_netif_init failed: %s", esp_err_to_name(err));
		return err;
	}

	s_sta_netif = esp_netif_create_default_wifi_sta();
	if (!s_sta_netif) {
		ESP_LOGE(NET_MGR_TAG, "Failed to create default STA netif");
		return ESP_FAIL;
	}

	s_ap_netif = esp_netif_create_default_wifi_ap();
	if (!s_ap_netif) {
		ESP_LOGE(NET_MGR_TAG, "Failed to create default AP netif");
		return ESP_FAIL;
	}

	wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
	err = esp_wifi_init(&cfg);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "esp_wifi_init failed: %s", esp_err_to_name(err));
		return err;
	}

	err = esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
					 &net_mgr_wifi_event_handler, NULL);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to register WIFI_EVENT handler: %s",
			 esp_err_to_name(err));
		return err;
	}

	err = esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
					 &net_mgr_wifi_event_handler, NULL);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to register IP_EVENT handler: %s",
			 esp_err_to_name(err));
		return err;
	}

	err = esp_event_handler_register(NET_MGR_EVENT, ESP_EVENT_ANY_ID,
					 &net_mgr_internal_event_handler, NULL);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to register NET_MGR_EVENT handler: %s",
			 esp_err_to_name(err));
		return err;
	}

	err = esp_wifi_set_mode(WIFI_MODE_STA);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to set STA mode: %s", esp_err_to_name(err));
		return err;
	}

	err = esp_wifi_start();
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to start Wi-Fi: %s", esp_err_to_name(err));
		return err;
	}

	esp_wifi_set_ps(WIFI_PS_NONE);
	ESP_LOGI(NET_MGR_TAG, "Wi-Fi power save disabled at init");

	esp_err_t proto_err = esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N);
	if (proto_err == ESP_OK) {
		ESP_LOGI(NET_MGR_TAG, "Wi-Fi 802.11ax (HE) disabled, using b/g/n only");
	} else {
		ESP_LOGW(NET_MGR_TAG, "Failed to disable 11ax: %s", esp_err_to_name(proto_err));
	}

	char ssid[NET_MGR_SSID_MAX_LEN + 1] = {0};
	char pass[NET_MGR_PASS_MAX_LEN + 1] = {0};
	size_t ssid_len = sizeof(ssid);
	size_t pass_len = sizeof(pass);

	if (net_mgr_load_credentials(ssid, &ssid_len, pass, &pass_len) == ESP_OK
	    && strlen(ssid) > 0) {
		ESP_LOGI(NET_MGR_TAG, "Saved credentials found, connecting to %s", ssid);
		return net_mgr_connect(ssid, pass);
	}

	ESP_LOGI(NET_MGR_TAG, "No saved credentials, starting provisioning");
	return net_mgr_start_provisioning();
}

esp_err_t net_mgr_start_provisioning(void)
{
	esp_err_t err;

	err = esp_wifi_stop();
	if (err != ESP_OK && err != ESP_ERR_WIFI_NOT_INIT) {
		ESP_LOGW(NET_MGR_TAG, "esp_wifi_stop returned: %s", esp_err_to_name(err));
	}

	err = esp_wifi_set_mode(WIFI_MODE_AP);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to set AP mode: %s", esp_err_to_name(err));
		return err;
	}

	uint8_t mac[6];
	err = esp_wifi_get_mac(WIFI_IF_STA, mac);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to get STA MAC: %s", esp_err_to_name(err));
		return err;
	}

	char ssid[33];
	snprintf(ssid, sizeof(ssid), "ZigbeeHUB-%02X%02X", mac[4], mac[5]);

	wifi_config_t wifi_config = {
		.ap = {
			.ssid_len     = strlen(ssid),
			.channel      = 1,
			.max_connection = 4,
			.authmode     = WIFI_AUTH_OPEN,
		},
	};
	memcpy(wifi_config.ap.ssid, ssid, strlen(ssid));

	err = esp_wifi_set_config(WIFI_IF_AP, &wifi_config);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to set AP config: %s", esp_err_to_name(err));
		return err;
	}

	err = esp_wifi_start();
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to start Wi-Fi in AP mode: %s", esp_err_to_name(err));
		return err;
	}

	ESP_LOGI(NET_MGR_TAG, "Provisioning AP started: %s", ssid);
	return ESP_OK;
}

esp_err_t net_mgr_connect(const char *ssid, const char *pass)
{
	if (!ssid || !pass) {
		return ESP_ERR_INVALID_ARG;
	}

	esp_err_t err = net_mgr_save_credentials(ssid, pass);
	if (err != ESP_OK) {
		return err;
	}

	err = esp_wifi_stop();
	if (err != ESP_OK && err != ESP_ERR_WIFI_NOT_INIT) {
		ESP_LOGW(NET_MGR_TAG, "esp_wifi_stop returned: %s", esp_err_to_name(err));
	}

	err = esp_wifi_set_mode(WIFI_MODE_STA);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to set STA mode: %s", esp_err_to_name(err));
		return err;
	}

	wifi_config_t wifi_config = {0};
	strncpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid) - 1);
	strncpy((char *)wifi_config.sta.password, pass, sizeof(wifi_config.sta.password) - 1);

	err = esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to set STA config: %s", esp_err_to_name(err));
		return err;
	}

	err = esp_wifi_start();
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to start Wi-Fi in STA mode: %s", esp_err_to_name(err));
		return err;
	}

	err = esp_wifi_connect();
	if (err != ESP_OK) {
		ESP_LOGE(NET_MGR_TAG, "Failed to start connection: %s", esp_err_to_name(err));
		return err;
	}

	s_reconnect_attempts = 0;
	ESP_LOGI(NET_MGR_TAG, "Connecting to %s", ssid);
	return ESP_OK;
}

esp_err_t net_mgr_erase_credentials(void)
{
	esp_err_t err = nvs_storage_erase(NET_MGR_WIFI_CFG_NS, NET_MGR_WIFI_SSID_KEY);
	if (err != ESP_OK && err != ESP_ERR_NOT_FOUND) {
		ESP_LOGW(NET_MGR_TAG, "Failed to erase SSID: %s", esp_err_to_name(err));
	}
	err = nvs_storage_erase(NET_MGR_WIFI_CFG_NS, NET_MGR_WIFI_PASS_KEY);
	if (err != ESP_OK && err != ESP_ERR_NOT_FOUND) {
		ESP_LOGW(NET_MGR_TAG, "Failed to erase password: %s", esp_err_to_name(err));
	}
	ESP_LOGI(NET_MGR_TAG, "Wi-Fi credentials erased");
	return ESP_OK;
}

bool net_mgr_is_connected(void)
{
	bool connected = false;
	if (s_mutex) {
		xSemaphoreTake(s_mutex, portMAX_DELAY);
		connected = s_connected;
		xSemaphoreGive(s_mutex);
	}
	return connected;
}

esp_err_t net_mgr_get_ip(char *buf, size_t len)
{
	if (!buf || len == 0) {
		return ESP_ERR_INVALID_ARG;
	}
	if (!s_mutex) {
		return ESP_ERR_INVALID_STATE;
	}

	xSemaphoreTake(s_mutex, portMAX_DELAY);
	strncpy(buf, s_ip_str, len - 1);
	buf[len - 1] = '\0';
	xSemaphoreGive(s_mutex);
	return ESP_OK;
}

esp_err_t net_mgr_register_provisioning_handler(httpd_handle_t server)
{
	if (server == NULL) {
		return ESP_ERR_INVALID_ARG;
	}
	return httpd_register_uri_handler(server, &provision_uri);
}
