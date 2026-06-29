#include "http_api.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "cJSON.h"
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

#include "zb_device_mgr.h"
#include "zb_clusters.h"
#include "zb_stack.h"
#include "net_mgr.h"
#include "color_utils.h"

static const char *TAG = "http_api";

static char s_api_key[HTTP_API_KEY_LEN] = {0};
static httpd_handle_t s_server = NULL;

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

static void generate_correlation_id(char *buf, size_t len)
{
	if (len < 33) {
		buf[0] = '\0';
		return;
	}
	for (int i = 0; i < 16; i++) {
		uint8_t b = (uint8_t)esp_random();
		snprintf(buf + i * 2, 3, "%02x", b);
	}
	buf[32] = '\0';
}

static bool check_api_key(httpd_req_t *req)
{
	char header[HTTP_API_KEY_LEN + 16];
	if (httpd_req_get_hdr_value_str(req, "X-API-Key", header, sizeof(header)) != ESP_OK) {
		return false;
	}
	return strcmp(header, s_api_key) == 0;
}

static esp_err_t send_json_response(httpd_req_t *req, int status, cJSON *root)
{
	const char *status_str = "200 OK";
	switch (status) {
		case 200: status_str = "200 OK"; break;
		case 202: status_str = "202 Accepted"; break;
		case 400: status_str = "400 Bad Request"; break;
		case 401: status_str = "401 Unauthorized"; break;
		case 404: status_str = "404 Not Found"; break;
		case 413: status_str = "413 Payload Too Large"; break;
		case 500: status_str = "500 Internal Server Error"; break;
	}

	char *resp = cJSON_PrintUnformatted(root);
	cJSON_Delete(root);
	if (!resp) {
		ESP_LOGE(TAG, "Failed to serialize JSON");
		return ESP_FAIL;
	}

	httpd_resp_set_status(req, status_str);
	httpd_resp_set_type(req, "application/json");
	esp_err_t ret = httpd_resp_sendstr(req, resp);
	free(resp);
	return ret;
}

static esp_err_t send_error(httpd_req_t *req, int status, const char *message)
{
	cJSON *root = cJSON_CreateObject();
	cJSON_AddStringToObject(root, "error", message);
	return send_json_response(req, status, root);
}

static esp_err_t send_accepted(httpd_req_t *req, const char *corr_id)
{
	cJSON *root = cJSON_CreateObject();
	cJSON_AddStringToObject(root, "correlation_id", corr_id);
	cJSON_AddStringToObject(root, "status", "pending");
	return send_json_response(req, 202, root);
}

static cJSON *endpoint_to_json(const zb_endpoint_info_t *ep)
{
	cJSON *obj = cJSON_CreateObject();
	cJSON_AddNumberToObject(obj, "id", ep->ep_id);
	cJSON *clusters = cJSON_CreateArray();
	for (uint8_t i = 0; i < ep->cluster_count; i++) {
		char buf[8];
		snprintf(buf, sizeof(buf), "0x%04X", ep->clusters[i]);
		cJSON_AddItemToArray(clusters, cJSON_CreateString(buf));
	}
	cJSON_AddItemToObject(obj, "clusters", clusters);
	cJSON_AddBoolToObject(obj, "supports_hs", ep->supports_hs);
	cJSON_AddBoolToObject(obj, "supports_xy", ep->supports_xy);
	cJSON_AddBoolToObject(obj, "supports_ct", ep->supports_ct);
	cJSON_AddBoolToObject(obj, "supports_color_loop", ep->supports_color_loop);
	return obj;
}

static cJSON *device_to_json(const zb_device_record_t *dev)
{
	cJSON *obj = cJSON_CreateObject();
	char ieee_str[32];
	snprintf(ieee_str, sizeof(ieee_str), "0x%016llX", (unsigned long long)dev->ieee_addr);
	cJSON_AddStringToObject(obj, "ieee_addr", ieee_str);
	cJSON_AddNumberToObject(obj, "network_addr", dev->network_addr);
	cJSON_AddNumberToObject(obj, "device_type", dev->device_type);
	cJSON_AddNumberToObject(obj, "power_source", dev->power_source);
	cJSON_AddStringToObject(obj, "friendly_name", dev->friendly_name);
	cJSON *endpoints = cJSON_CreateArray();
	for (uint8_t i = 0; i < dev->endpoint_count; i++) {
		cJSON_AddItemToArray(endpoints, endpoint_to_json(&dev->endpoints[i]));
	}
	cJSON_AddItemToObject(obj, "endpoints", endpoints);
	return obj;
}

static bool parse_ieee_and_suffix(const char *uri, uint64_t *ieee, char *suffix, size_t suffix_len)
{
	const char *prefix = "/devices/";
	if (strncmp(uri, prefix, strlen(prefix)) != 0) {
		return false;
	}
	const char *p = uri + strlen(prefix);
	char *endptr = NULL;
	*ieee = strtoull(p, &endptr, 0);
	if (endptr == p) {
		return false;
	}
	if (*endptr == '\0') {
		suffix[0] = '\0';
		return true;
	}
	if (*endptr == '/') {
		strncpy(suffix, endptr + 1, suffix_len - 1);
		suffix[suffix_len - 1] = '\0';
		return true;
	}
	return false;
}

/* -------------------------------------------------------------------------- */
/* Handlers                                                                   */
/* -------------------------------------------------------------------------- */

static esp_err_t health_get_handler(httpd_req_t *req)
{
	if (!check_api_key(req)) {
		return send_error(req, 401, "Unauthorized");
	}

	cJSON *root = cJSON_CreateObject();
	cJSON_AddStringToObject(root, "status", "ok");
	cJSON_AddStringToObject(root, "network", net_mgr_is_connected() ? "connected" : "disconnected");
	cJSON_AddNumberToObject(root, "uptime_ms", (double)(esp_timer_get_time() / 1000LL));
	return send_json_response(req, 200, root);
}

static esp_err_t devices_list_get_handler(httpd_req_t *req)
{
	if (!check_api_key(req)) {
		return send_error(req, 401, "Unauthorized");
	}

	uint8_t count = 0;
	const zb_device_record_t *devices = zb_device_mgr_get_all(&count);
	cJSON *arr = cJSON_CreateArray();
	for (uint8_t i = 0; i < count; i++) {
		cJSON_AddItemToArray(arr, device_to_json(&devices[i]));
	}
	return send_json_response(req, 200, arr);
}

static esp_err_t devices_get_handler(httpd_req_t *req)
{
	if (!check_api_key(req)) {
		return send_error(req, 401, "Unauthorized");
	}

	uint64_t ieee = 0;
	char suffix[64] = {0};
	if (!parse_ieee_and_suffix(req->uri, &ieee, suffix, sizeof(suffix))) {
		return send_error(req, 400, "Invalid IEEE address");
	}

	const zb_device_record_t *dev = zb_device_mgr_get(ieee);
	if (!dev) {
		return send_error(req, 404, "Device not found");
	}

	if (strlen(suffix) == 0) {
		/* GET /devices/{ieee} */
		return send_json_response(req, 200, device_to_json(dev));
	}

	if (strcmp(suffix, "color-capabilities") == 0) {
		cJSON *root = cJSON_CreateObject();
		const zb_endpoint_info_t *ep = zb_device_mgr_find_ep_with_cluster(ieee, 0x0300);
		if (ep) {
			cJSON_AddBoolToObject(root, "supports_hs", ep->supports_hs);
			cJSON_AddBoolToObject(root, "supports_xy", ep->supports_xy);
			cJSON_AddBoolToObject(root, "supports_ct", ep->supports_ct);
			cJSON_AddBoolToObject(root, "supports_color_loop", ep->supports_color_loop);
		} else {
			cJSON_AddBoolToObject(root, "supports_hs", false);
			cJSON_AddBoolToObject(root, "supports_xy", false);
			cJSON_AddBoolToObject(root, "supports_ct", false);
			cJSON_AddBoolToObject(root, "supports_color_loop", false);
		}
		return send_json_response(req, 200, root);
	}

	return send_error(req, 404, "Not found");
}

static esp_err_t devices_post_handler(httpd_req_t *req)
{
	if (!check_api_key(req)) {
		return send_error(req, 401, "Unauthorized");
	}

	uint64_t ieee = 0;
	char suffix[64] = {0};
	if (!parse_ieee_and_suffix(req->uri, &ieee, suffix, sizeof(suffix))) {
		return send_error(req, 400, "Invalid IEEE address");
	}

	if (zb_device_mgr_get(ieee) == NULL) {
		return send_error(req, 404, "Device not found");
	}

	char corr_id[40] = {0};
	generate_correlation_id(corr_id, sizeof(corr_id));

	/* On/Off commands */
	if (strcmp(suffix, "on") == 0) {
		esp_err_t err = zb_cluster_send_on_off(ieee, ZB_CMD_ON_OFF_ON, corr_id, 0);
		if (err != ESP_OK) {
			ESP_LOGE(TAG, "zb_cluster_send_on_off failed: %s", esp_err_to_name(err));
			return send_error(req, 500, "Failed to send command");
		}
		return send_accepted(req, corr_id);
	}
	if (strcmp(suffix, "off") == 0) {
		esp_err_t err = zb_cluster_send_on_off(ieee, ZB_CMD_ON_OFF_OFF, corr_id, 0);
		if (err != ESP_OK) {
			ESP_LOGE(TAG, "zb_cluster_send_on_off failed: %s", esp_err_to_name(err));
			return send_error(req, 500, "Failed to send command");
		}
		return send_accepted(req, corr_id);
	}
	if (strcmp(suffix, "toggle") == 0) {
		esp_err_t err = zb_cluster_send_on_off(ieee, ZB_CMD_ON_OFF_TOGGLE, corr_id, 0);
		if (err != ESP_OK) {
			ESP_LOGE(TAG, "zb_cluster_send_on_off failed: %s", esp_err_to_name(err));
			return send_error(req, 500, "Failed to send command");
		}
		return send_accepted(req, corr_id);
	}

	/* Read body for level, color and other endpoints */
	char body[512];
	if (req->content_len >= (int)sizeof(body)) {
		httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Body too large");
		return ESP_FAIL;
	}
	int ret = httpd_req_recv(req, body, sizeof(body) - 1);
	if (ret <= 0) {
		ESP_LOGE(TAG, "Failed to read body: %d", ret);
		return send_error(req, 400, "Invalid body");
	}
	body[ret] = '\0';

	if (strcmp(suffix, "level") == 0) {
		cJSON *root = cJSON_Parse(body);
		if (!root) {
			return send_error(req, 400, "Invalid JSON");
		}
		cJSON *level_item = cJSON_GetObjectItem(root, "level");
		cJSON *trans_item = cJSON_GetObjectItem(root, "transition");
		if (!cJSON_IsNumber(level_item) || !cJSON_IsNumber(trans_item)) {
			cJSON_Delete(root);
			return send_error(req, 400, "Missing level or transition");
		}
		uint8_t level = (uint8_t)cJSON_GetNumberValue(level_item);
		double trans_sec = cJSON_GetNumberValue(trans_item);
		uint16_t transition = (uint16_t)(trans_sec * 10.0 + 0.5);
		cJSON_Delete(root);

		esp_err_t err = zb_cluster_send_level(ieee, level, transition, corr_id, 0);
		if (err != ESP_OK) {
			ESP_LOGE(TAG, "zb_cluster_send_level failed: %s", esp_err_to_name(err));
			return send_error(req, 500, "Failed to send command");
		}
		return send_accepted(req, corr_id);
	}

	if (strcmp(suffix, "color") == 0) {
		cJSON *root = cJSON_Parse(body);
		if (!root) {
			return send_error(req, 400, "Invalid JSON");
		}

		cJSON *hex_item = cJSON_GetObjectItem(root, "hex");
		cJSON *mode_item = cJSON_GetObjectItem(root, "mode");
		cJSON *level_item = cJSON_GetObjectItem(root, "level");
		cJSON *trans_item = cJSON_GetObjectItem(root, "transition");

		esp_err_t err = ESP_OK;

		if (cJSON_IsString(hex_item)) {
			uint8_t r, g, b;
			if (!color_utils_hex_to_rgb(hex_item->valuestring, &r, &g, &b)) {
				cJSON_Delete(root);
				return send_error(req, 400, "Invalid hex color");
			}

			if (!cJSON_IsNumber(trans_item)) {
				cJSON_Delete(root);
				return send_error(req, 400, "Missing transition");
			}
			double trans_sec = cJSON_GetNumberValue(trans_item);
			uint16_t transition = (uint16_t)(trans_sec * 10.0 + 0.5);

			bool send_hs = false;
			bool send_xy = false;

			if (cJSON_IsString(mode_item)) {
				if (strcmp(mode_item->valuestring, "hs") == 0) {
					send_hs = true;
				} else if (strcmp(mode_item->valuestring, "xy") == 0) {
					send_xy = true;
				} else {
					cJSON_Delete(root);
					return send_error(req, 400, "Unsupported color mode");
				}
			} else {
				const zb_endpoint_info_t *color_ep = zb_device_mgr_find_ep_with_cluster(ieee, 0x0300);
				if (color_ep && color_ep->supports_hs) {
					send_hs = true;
				} else if (color_ep && color_ep->supports_xy) {
					send_xy = true;
				} else {
					cJSON_Delete(root);
					return send_error(req, 400, "Device does not support color control");
				}
			}

			if (send_hs) {
				uint8_t hue, sat;
				color_utils_rgb_to_hsv(r, g, b, &hue, &sat);
				err = zb_cluster_send_color_hs(ieee, hue, sat, transition, corr_id, 0);
			} else if (send_xy) {
				uint16_t x, y;
				color_utils_rgb_to_xy(r, g, b, &x, &y);
				err = zb_cluster_send_color_xy(ieee, x, y, transition, corr_id, 0);
			}

			if (err == ESP_OK && cJSON_IsNumber(level_item)) {
				uint8_t level = (uint8_t)cJSON_GetNumberValue(level_item);
				err = zb_cluster_send_level(ieee, level, transition, corr_id, 0);
			}

			cJSON_Delete(root);

			if (err != ESP_OK) {
				ESP_LOGE(TAG, "zb_cluster_send_color_* or level failed: %s", esp_err_to_name(err));
				return send_error(req, 500, "Failed to send command");
			}
			return send_accepted(req, corr_id);
		}

		if (!cJSON_IsString(mode_item)) {
			cJSON_Delete(root);
			return send_error(req, 400, "Missing mode or hex");
		}
		const char *mode = mode_item->valuestring;

		if (strcmp(mode, "hs") == 0) {
			cJSON *hue_item = cJSON_GetObjectItem(root, "hue");
			cJSON *sat_item = cJSON_GetObjectItem(root, "saturation");
			cJSON *trans_item = cJSON_GetObjectItem(root, "transition");
			if (!cJSON_IsNumber(hue_item) || !cJSON_IsNumber(sat_item) || !cJSON_IsNumber(trans_item)) {
				cJSON_Delete(root);
				return send_error(req, 400, "Missing hue, saturation or transition");
			}
			uint8_t hue = (uint8_t)cJSON_GetNumberValue(hue_item);
			uint8_t sat = (uint8_t)cJSON_GetNumberValue(sat_item);
			double trans_sec = cJSON_GetNumberValue(trans_item);
			uint16_t transition = (uint16_t)(trans_sec * 10.0 + 0.5);
			cJSON_Delete(root);
			err = zb_cluster_send_color_hs(ieee, hue, sat, transition, corr_id, 0);
		} else if (strcmp(mode, "xy") == 0) {
			cJSON *x_item = cJSON_GetObjectItem(root, "x");
			cJSON *y_item = cJSON_GetObjectItem(root, "y");
			cJSON *trans_item = cJSON_GetObjectItem(root, "transition");
			if (!cJSON_IsNumber(x_item) || !cJSON_IsNumber(y_item) || !cJSON_IsNumber(trans_item)) {
				cJSON_Delete(root);
				return send_error(req, 400, "Missing x, y or transition");
			}
			uint16_t x = (uint16_t)cJSON_GetNumberValue(x_item);
			uint16_t y = (uint16_t)cJSON_GetNumberValue(y_item);
			double trans_sec = cJSON_GetNumberValue(trans_item);
			uint16_t transition = (uint16_t)(trans_sec * 10.0 + 0.5);
			cJSON_Delete(root);
			err = zb_cluster_send_color_xy(ieee, x, y, transition, corr_id, 0);
		} else {
			cJSON_Delete(root);
			return send_error(req, 400, "Unsupported color mode");
		}

		if (err != ESP_OK) {
			ESP_LOGE(TAG, "zb_cluster_send_color_* failed: %s", esp_err_to_name(err));
			return send_error(req, 500, "Failed to send command");
		}
		return send_accepted(req, corr_id);
	}

	return send_error(req, 404, "Not found");
}

static esp_err_t network_permit_join_post_handler(httpd_req_t *req)
{
	if (!check_api_key(req)) {
		return send_error(req, 401, "Unauthorized");
	}

	char body[128];
	if (req->content_len >= (int)sizeof(body)) {
		httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Body too large");
		return ESP_FAIL;
	}
	int ret = httpd_req_recv(req, body, sizeof(body) - 1);
	if (ret <= 0) {
		ESP_LOGE(TAG, "Failed to read body: %d", ret);
		return send_error(req, 400, "Invalid body");
	}
	body[ret] = '\0';

	cJSON *root = cJSON_Parse(body);
	if (!root) {
		return send_error(req, 400, "Invalid JSON");
	}
	cJSON *dur_item = cJSON_GetObjectItem(root, "duration");
	if (!cJSON_IsNumber(dur_item)) {
		cJSON_Delete(root);
		return send_error(req, 400, "Missing duration");
	}
	uint8_t duration = (uint8_t)cJSON_GetNumberValue(dur_item);
	cJSON_Delete(root);

	char corr_id[40] = {0};
	generate_correlation_id(corr_id, sizeof(corr_id));

	esp_err_t err = zb_stack_permit_join(duration);
	if (err != ESP_OK) {
		ESP_LOGE(TAG, "zb_stack_permit_join failed: %s", esp_err_to_name(err));
		return send_error(req, 500, "Failed to permit join");
	}
	return send_accepted(req, corr_id);
}

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

void http_api_set_api_key(const char *api_key)
{
	if (!api_key) {
		s_api_key[0] = '\0';
		return;
	}
	strncpy(s_api_key, api_key, sizeof(s_api_key) - 1);
	s_api_key[sizeof(s_api_key) - 1] = '\0';
}

esp_err_t http_api_init(void)
{
	if (s_server) {
		return ESP_OK;
	}

	httpd_config_t config = HTTPD_DEFAULT_CONFIG();
	config.server_port = 80;
	config.uri_match_fn = httpd_uri_match_wildcard;

	esp_err_t ret = httpd_start(&s_server, &config);
	if (ret != ESP_OK) {
		ESP_LOGE(TAG, "Failed to start http server: %s", esp_err_to_name(ret));
		return ret;
	}

	httpd_uri_t health_uri = {
		.uri      = "/health",
		.method   = HTTP_GET,
		.handler  = health_get_handler,
		.user_ctx = NULL,
	};

	httpd_uri_t devices_list_uri = {
		.uri      = "/devices",
		.method   = HTTP_GET,
		.handler  = devices_list_get_handler,
		.user_ctx = NULL,
	};

	httpd_uri_t devices_get_uri = {
		.uri      = "/devices/*",
		.method   = HTTP_GET,
		.handler  = devices_get_handler,
		.user_ctx = NULL,
	};

	httpd_uri_t devices_post_uri = {
		.uri      = "/devices/*",
		.method   = HTTP_POST,
		.handler  = devices_post_handler,
		.user_ctx = NULL,
	};

	httpd_uri_t permit_join_uri = {
		.uri      = "/network/permit-join",
		.method   = HTTP_POST,
		.handler  = network_permit_join_post_handler,
		.user_ctx = NULL,
	};

	httpd_uri_t *uris[] = {
		&health_uri,
		&devices_list_uri,
		&devices_get_uri,
		&devices_post_uri,
		&permit_join_uri
	};

	for (int i = 0; i < sizeof(uris) / sizeof(uris[0]); i++) {
		ret = httpd_register_uri_handler(s_server, uris[i]);
		if (ret != ESP_OK) {
			ESP_LOGE(TAG, "Failed to register URI handler: %s", esp_err_to_name(ret));
			return ret;
		}
	}

	esp_err_t prov_err = net_mgr_register_provisioning_handler(s_server);
	if (prov_err != ESP_OK) {
		ESP_LOGW(TAG, "Failed to register provisioning handler: %s", esp_err_to_name(prov_err));
	}

	ESP_LOGI(TAG, "HTTP API server started on port %d", config.server_port);
	return ESP_OK;
}
