#include "serial_api.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "cJSON.h"

#include "zb_device_mgr.h"
#include "zb_clusters.h"
#include "zb_stack.h"
#include "com_pipeline.h"
#include "color_utils.h"

static const char *TAG = "serial_api";
static SemaphoreHandle_t s_stdout_mutex = NULL;

#define MAX_PENDING_PINGS 32

typedef struct {
	bool     active;
	char     corr_id[COM_CORR_ID_LEN];
	uint64_t ieee;
} pending_ping_t;

static pending_ping_t s_pending_pings[MAX_PENDING_PINGS];

/* Forward declarations */
static void send_json_line(cJSON *root);

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

static uint64_t parse_ieee(const char *str)
{
	return strtoull(str, NULL, 0);
}

static void register_pending_ping(const char *corr_id, uint64_t ieee)
{
	if (!corr_id) {
		return;
	}
	for (int i = 0; i < MAX_PENDING_PINGS; i++) {
		if (!s_pending_pings[i].active) {
			s_pending_pings[i].active = true;
			s_pending_pings[i].ieee = ieee;
			strncpy(s_pending_pings[i].corr_id, corr_id, COM_CORR_ID_LEN - 1);
			s_pending_pings[i].corr_id[COM_CORR_ID_LEN - 1] = '\0';
			return;
		}
	}
	ESP_LOGW(TAG, "Pending ping table full");
}

static pending_ping_t *find_pending_ping(const char *corr_id)
{
	if (!corr_id) {
		return NULL;
	}
	for (int i = 0; i < MAX_PENDING_PINGS; i++) {
		if (s_pending_pings[i].active &&
		    strcmp(s_pending_pings[i].corr_id, corr_id) == 0) {
			return &s_pending_pings[i];
		}
	}
	return NULL;
}

static void clear_pending_ping(pending_ping_t *ping)
{
	if (ping) {
		ping->active = false;
		ping->corr_id[0] = '\0';
		ping->ieee = 0ULL;
	}
}

static void emit_ping_result(uint64_t ieee, const char *corr_id, bool online)
{
	cJSON *root = cJSON_CreateObject();
	cJSON_AddStringToObject(root, "evt", "ping_result");
	char ieee_str[32];
	snprintf(ieee_str, sizeof(ieee_str), "0x%016llX", (unsigned long long)ieee);
	cJSON_AddStringToObject(root, "ieee", ieee_str);
	if (corr_id) {
		cJSON_AddStringToObject(root, "correlation_id", corr_id);
	}
	cJSON_AddBoolToObject(root, "online", online);
	send_json_line(root);
	cJSON_Delete(root);
}

static void send_json_line(cJSON *root)
{
	char *out = cJSON_PrintUnformatted(root);
	if (out) {
		if (s_stdout_mutex) {
			xSemaphoreTake(s_stdout_mutex, portMAX_DELAY);
		}
		printf("%s\n", out);
		fflush(stdout);
		if (s_stdout_mutex) {
			xSemaphoreGive(s_stdout_mutex);
		}
		cJSON_free(out);
	}
}

/* -------------------------------------------------------------------------- */
/* Command handlers                                                           */
/* -------------------------------------------------------------------------- */

static void handle_list(void)
{
	uint8_t count = 0;
	const zb_device_record_t *devs = zb_device_mgr_get_all(&count);
	cJSON *root = cJSON_CreateObject();
	cJSON_AddStringToObject(root, "evt", "device_list");
	cJSON *arr = cJSON_CreateArray();
	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (devs[i].ieee_addr != 0ULL) {
			cJSON *obj = cJSON_CreateObject();
			char ieee_str[32];
			snprintf(ieee_str, sizeof(ieee_str), "0x%016llX", (unsigned long long)devs[i].ieee_addr);
			cJSON_AddStringToObject(obj, "ieee_addr", ieee_str);
			cJSON_AddNumberToObject(obj, "network_addr", devs[i].network_addr);
			cJSON_AddBoolToObject(obj, "online", zb_device_mgr_is_online(devs[i].ieee_addr));
			cJSON_AddNumberToObject(obj, "last_seen_ms", zb_device_mgr_get_last_seen_ms(devs[i].ieee_addr));
			cJSON_AddNumberToObject(obj, "endpoint_count", devs[i].endpoint_count);
			cJSON *eps = cJSON_CreateArray();
			for (uint8_t e = 0; e < devs[i].endpoint_count; e++) {
				cJSON *ep_obj = cJSON_CreateObject();
				cJSON_AddNumberToObject(ep_obj, "id", devs[i].endpoints[e].ep_id);
				cJSON *cl_arr = cJSON_CreateArray();
				for (uint8_t c = 0; c < devs[i].endpoints[e].cluster_count; c++) {
					cJSON_AddItemToArray(cl_arr, cJSON_CreateNumber(devs[i].endpoints[e].clusters[c]));
				}
				cJSON_AddItemToObject(ep_obj, "clusters", cl_arr);
				cJSON_AddItemToArray(eps, ep_obj);
			}
			cJSON_AddItemToObject(obj, "endpoints", eps);
			cJSON_AddItemToArray(arr, obj);
		}
	}
	cJSON_AddItemToObject(root, "devices", arr);
	send_json_line(root);
	cJSON_Delete(root);
}

static void ack_cmd(const char *evt_name, const char *ieee_str, esp_err_t err,
                    const char *corr_id)
{
	cJSON *root = cJSON_CreateObject();
	cJSON_AddStringToObject(root, "evt", evt_name);
	cJSON_AddStringToObject(root, "ieee", ieee_str ? ieee_str : "");
	cJSON_AddBoolToObject(root, "ok", err == ESP_OK);
	if (corr_id && corr_id[0] != '\0') {
		cJSON_AddStringToObject(root, "correlation_id", corr_id);
	}
	if (err != ESP_OK) {
		cJSON_AddStringToObject(root, "error", esp_err_to_name(err));
	}
	send_json_line(root);
	cJSON_Delete(root);
}

static void handle_on(const char *ieee_str, uint8_t ep_id, const char *corr_id)
{
	ESP_LOGI(TAG, "handle_on %s ep=%u", ieee_str, ep_id);
	uint64_t ieee = parse_ieee(ieee_str);
	esp_err_t err = zb_cluster_send_on_off(ieee, ZB_CMD_ON_OFF_ON, corr_id, ep_id);
	ESP_LOGI(TAG, "handle_on result %s", esp_err_to_name(err));
	ack_cmd("on_ack", ieee_str, err, corr_id);
}

static void handle_off(const char *ieee_str, uint8_t ep_id, const char *corr_id)
{
	ESP_LOGI(TAG, "handle_off %s ep=%u", ieee_str, ep_id);
	uint64_t ieee = parse_ieee(ieee_str);
	esp_err_t err = zb_cluster_send_on_off(ieee, ZB_CMD_ON_OFF_OFF, corr_id, ep_id);
	ESP_LOGI(TAG, "handle_off result %s", esp_err_to_name(err));
	ack_cmd("off_ack", ieee_str, err, corr_id);
}

static void handle_toggle(const char *ieee_str, uint8_t ep_id, const char *corr_id)
{
	ESP_LOGI(TAG, "handle_toggle %s ep=%u", ieee_str, ep_id);
	uint64_t ieee = parse_ieee(ieee_str);
	esp_err_t err = zb_cluster_send_on_off(ieee, ZB_CMD_ON_OFF_TOGGLE, corr_id, ep_id);
	ESP_LOGI(TAG, "handle_toggle result %s", esp_err_to_name(err));
	ack_cmd("toggle_ack", ieee_str, err, corr_id);
}

static void handle_level(const char *ieee_str, uint8_t level,
                           uint16_t transition, uint8_t ep_id, const char *corr_id)
{
	ESP_LOGI(TAG, "handle_level %s -> %d trans=%u ep=%u",
		 ieee_str, level, transition, ep_id);
	uint64_t ieee = parse_ieee(ieee_str);
	esp_err_t err = zb_cluster_send_level(ieee, level, transition, corr_id, ep_id);
	ESP_LOGI(TAG, "handle_level result %s", esp_err_to_name(err));
	ack_cmd("level_ack", ieee_str, err, corr_id);
}

static void handle_color(const char *ieee_str, const char *hex,
                           const char *mode, uint16_t transition, uint8_t ep_id,
                           const char *corr_id)
{
	ESP_LOGI(TAG, "handle_color %s -> %s mode=%s trans=%u ep=%u",
		 ieee_str, hex, mode ? mode : "null", transition, ep_id);
	uint64_t ieee = parse_ieee(ieee_str);

	const zb_endpoint_info_t *ep = NULL;
	if (ep_id != 0) {
		ep = zb_device_mgr_get_endpoint(ieee, ep_id);
	} else {
		ep = zb_device_mgr_find_ep_with_cluster(ieee, 0x0300);
	}
	if (!ep) {
		ack_cmd("color_ack", ieee_str, ESP_ERR_NOT_FOUND, corr_id);
		return;
	}

	uint8_t r, g, b;
	if (!color_utils_hex_to_rgb(hex, &r, &g, &b)) {
		ack_cmd("color_ack", ieee_str, ESP_ERR_INVALID_ARG, corr_id);
		return;
	}

	esp_err_t err = ESP_ERR_INVALID_ARG;
	if (mode && strcmp(mode, "hs") == 0) {
		uint8_t h, s;
		color_utils_rgb_to_hsv(r, g, b, &h, &s);
		err = zb_cluster_send_color_hs(ieee, h, s, transition, corr_id, ep->ep_id);
	} else if (mode && strcmp(mode, "xy") == 0) {
		uint16_t x, y;
		color_utils_rgb_to_xy(r, g, b, &x, &y);
		err = zb_cluster_send_color_xy(ieee, x, y, transition, corr_id, ep->ep_id);
	}
	ESP_LOGI(TAG, "handle_color result %s", esp_err_to_name(err));
	ack_cmd("color_ack", ieee_str, err, corr_id);
}

static void handle_color_ct(const char *ieee_str, uint16_t mireds,
                              uint16_t transition, uint8_t ep_id,
                              const char *corr_id)
{
	ESP_LOGI(TAG, "handle_color_ct %s -> %u trans=%u ep=%u",
		 ieee_str, mireds, transition, ep_id);
	uint64_t ieee = parse_ieee(ieee_str);

	const zb_endpoint_info_t *ep = NULL;
	if (ep_id != 0) {
		ep = zb_device_mgr_get_endpoint(ieee, ep_id);
	} else {
		ep = zb_device_mgr_find_ep_with_cluster(ieee, 0x0300);
	}
	if (!ep) {
		ack_cmd("color_ct_ack", ieee_str, ESP_ERR_NOT_FOUND, corr_id);
		return;
	}

	esp_err_t err = zb_cluster_send_color_ct(ieee, mireds, transition, corr_id, ep->ep_id);
	ESP_LOGI(TAG, "handle_color_ct result %s", esp_err_to_name(err));
	ack_cmd("color_ct_ack", ieee_str, err, corr_id);
}

static void handle_read_attr(const char *ieee_str, uint8_t ep_id,
                             const char *cluster_str, const char *attr_str,
                             const char *corr_id)
{
	ESP_LOGI(TAG, "handle_read_attr %s ep=%u cluster=%s attr=%s",
		 ieee_str, ep_id, cluster_str, attr_str);
	uint64_t ieee = parse_ieee(ieee_str);
	uint16_t cluster_id = (uint16_t)strtoul(cluster_str, NULL, 0);
	uint16_t attr_id = (uint16_t)strtoul(attr_str, NULL, 0);
	esp_err_t err = zb_cluster_read_attr(ieee, ep_id, cluster_id, attr_id, corr_id);
	ack_cmd("read_attr_ack", ieee_str, err, corr_id);
}

static void handle_permit(uint8_t duration)
{
	esp_err_t err = zb_stack_permit_join(duration);
	cJSON *root = cJSON_CreateObject();
	cJSON_AddStringToObject(root, "evt", "permit_join");
	cJSON_AddNumberToObject(root, "duration", duration);
	cJSON_AddBoolToObject(root, "ok", err == ESP_OK);
	send_json_line(root);
	cJSON_Delete(root);
}

static void handle_ping(const char *ieee_str, const char *corr_id)
{
	ESP_LOGI(TAG, "handle_ping %s", ieee_str);
	uint64_t ieee = parse_ieee(ieee_str);
	register_pending_ping(corr_id, ieee);
	esp_err_t err = zb_cluster_ping(ieee, corr_id);
	if (err != ESP_OK) {
		clear_pending_ping(find_pending_ping(corr_id));
		emit_ping_result(ieee, corr_id, false);
	}
}

/* -------------------------------------------------------------------------- */
/* Event subscriber                                                           */
/* -------------------------------------------------------------------------- */

static void serial_event_handler(const com_event_t *evt, void *user_data)
{
	(void)user_data;
	cJSON *root = cJSON_CreateObject();
	bool suppress_json = false;

	switch (evt->type) {
	case COM_EVT_CONNECTED:
		cJSON_AddStringToObject(root, "evt", "connected");
		break;
	case COM_EVT_DEVICE_JOINED: {
		cJSON_AddStringToObject(root, "evt", "device_joined");
		char ieee_str[32];
		snprintf(ieee_str, sizeof(ieee_str), "0x%016llX", (unsigned long long)evt->payload.device_joined.ieee_addr);
		cJSON_AddStringToObject(root, "ieee_addr", ieee_str);
		cJSON_AddNumberToObject(root, "network_addr", evt->payload.device_joined.network_addr);
		cJSON_AddNumberToObject(root, "device_type", evt->payload.device_joined.device_type);
		break;
	}
	case COM_EVT_DEVICE_LEFT: {
		cJSON_AddStringToObject(root, "evt", "device_left");
		char ieee_str[32];
		snprintf(ieee_str, sizeof(ieee_str), "0x%016llX", (unsigned long long)evt->payload.device_left.ieee_addr);
		cJSON_AddStringToObject(root, "ieee_addr", ieee_str);
		break;
	}
	case COM_EVT_STATE_CHANGE: {
		cJSON_AddStringToObject(root, "evt", "state_change");
		char ieee_str[32];
		snprintf(ieee_str, sizeof(ieee_str), "0x%016llX", (unsigned long long)evt->payload.state_change.ieee_addr);
		cJSON_AddStringToObject(root, "ieee_addr", ieee_str);
		cJSON_AddNumberToObject(root, "num_changes", evt->payload.state_change.num_changes);
		cJSON *changes = cJSON_CreateArray();
		if (changes) {
			for (uint8_t i = 0; i < evt->payload.state_change.num_changes; i++) {
				cJSON *item = cJSON_CreateObject();
				if (item) {
					cJSON_AddStringToObject(item, "cluster", evt->payload.state_change.changes[i].cluster);
					cJSON_AddStringToObject(item, "attribute", evt->payload.state_change.changes[i].attribute);
					cJSON_AddNumberToObject(item, "endpoint", evt->payload.state_change.changes[i].endpoint);
					switch (evt->payload.state_change.changes[i].type) {
					case 0: cJSON_AddBoolToObject(item, "value", evt->payload.state_change.changes[i].value.b_val); break;
					case 1: cJSON_AddNumberToObject(item, "value", evt->payload.state_change.changes[i].value.i_val); break;
					case 2: cJSON_AddNumberToObject(item, "value", evt->payload.state_change.changes[i].value.u_val); break;
					case 3: cJSON_AddNumberToObject(item, "value", evt->payload.state_change.changes[i].value.f_val); break;
					default: cJSON_AddNullToObject(item, "value"); break;
					}
					cJSON_AddItemToArray(changes, item);
				}
			}
			cJSON_AddItemToObject(root, "changes", changes);
		}
		break;
	}
	case COM_EVT_COMMAND_FAILED: {
		cJSON_AddStringToObject(root, "evt", "command_failed");
		cJSON_AddStringToObject(root, "correlation_id", evt->payload.command_failed.correlation_id);
		cJSON_AddStringToObject(root, "error", evt->payload.command_failed.error);
		cJSON_AddStringToObject(root, "message", evt->payload.command_failed.message);
		break;
	}
	case COM_EVT_COMMAND_STATUS: {
		cJSON_AddStringToObject(root, "evt", "command_status");
		cJSON_AddStringToObject(root, "correlation_id", evt->payload.command_status.correlation_id);
		const char *status_str = "unknown";
		com_cmd_status_t status = evt->payload.command_status.status;
		switch (status) {
			case CMD_STATUS_PENDING:   status_str = "pending";   break;
			case CMD_STATUS_DELIVERED: status_str = "delivered"; break;
			case CMD_STATUS_COMPLETED: status_str = "completed"; break;
			case CMD_STATUS_FAILED:    status_str = "failed";    break;
			case CMD_STATUS_TIMEOUT:   status_str = "timeout";   break;
		}
		cJSON_AddStringToObject(root, "status", status_str);
		if (evt->payload.command_status.reason[0] != '\0') {
			cJSON_AddStringToObject(root, "reason", evt->payload.command_status.reason);
		}
		if (evt->payload.command_status.ieee_addr != 0ULL) {
			char ieee_str[32];
			snprintf(ieee_str, sizeof(ieee_str), "0x%016llX",
				 (unsigned long long)evt->payload.command_status.ieee_addr);
			cJSON_AddStringToObject(root, "ieee_addr", ieee_str);
		}
		if (evt->payload.command_status.cluster_id != 0) {
			cJSON_AddNumberToObject(root, "cluster_id", evt->payload.command_status.cluster_id);
		}

		const char *corr_id = evt->payload.command_status.correlation_id;
		pending_ping_t *ping = find_pending_ping(corr_id);
		if (ping) {
			bool online = (status == CMD_STATUS_COMPLETED ||
				       status == CMD_STATUS_DELIVERED);
			if (online) {
				zb_device_mgr_touch_last_seen(ping->ieee);
			} else if (status == CMD_STATUS_TIMEOUT || status == CMD_STATUS_FAILED) {
				zb_device_mgr_set_online(ping->ieee, false);
			}
			emit_ping_result(ping->ieee, corr_id, online);
			clear_pending_ping(ping);
			/* Ping lifecycle is complete; do not also emit command_status. */
			suppress_json = true;
		}
		break;
	}
	default:
		cJSON_Delete(root);
		return;
	}

	if (!suppress_json) {
		send_json_line(root);
	}
	cJSON_Delete(root);
}

/* -------------------------------------------------------------------------- */
/* Serial task                                                                */
/* -------------------------------------------------------------------------- */

static bool read_line(char *buf, size_t buf_len)
{
	size_t i = 0;
	while (i < buf_len - 1) {
		int c = getchar();
		if (c == EOF || c == 0) {
			vTaskDelay(1); /* 1 tick = 10 ms @ 100 Hz */
			continue;
		}
		if (c == '\n' || c == '\r') {
			if (i == 0) {
				continue; /* skip empty lines */
			}
			buf[i] = '\0';
			return true;
		}
		buf[i++] = (char)c;
	}
	buf[i] = '\0';
	return true;
}

static void serial_task(void *arg)
{
	(void)arg;
	char line[256];

	setvbuf(stdin, NULL, _IONBF, 0);
	setvbuf(stdout, NULL, _IONBF, 0);

	while (1) {
		if (read_line(line, sizeof(line))) {
			if (strlen(line) == 0) {
				continue;
			}

			cJSON *root = cJSON_Parse(line);
			if (!root) {
				ESP_LOGW(TAG, "Failed to parse JSON line: '%s'", line);
				cJSON *err = cJSON_CreateObject();
				cJSON_AddStringToObject(err, "evt", "error");
				cJSON_AddStringToObject(err, "message", "invalid_json");
				send_json_line(err);
				cJSON_Delete(err);
				continue;
			}

			cJSON *cmd = cJSON_GetObjectItem(root, "cmd");
			if (!cJSON_IsString(cmd)) {
				cJSON_Delete(root);
				cJSON *err = cJSON_CreateObject();
				cJSON_AddStringToObject(err, "evt", "error");
				cJSON_AddStringToObject(err, "message", "missing_cmd");
				send_json_line(err);
				cJSON_Delete(err);
				continue;
			}

			const char *cmd_str = cmd->valuestring;

			const char *corr_id = NULL;
			cJSON *corr_item = cJSON_GetObjectItem(root, "correlation_id");
			if (cJSON_IsString(corr_item)) {
				corr_id = corr_item->valuestring;
			}

			uint8_t ep_id = 0;
			cJSON *ep_item = cJSON_GetObjectItem(root, "endpoint");
			if (cJSON_IsNumber(ep_item)) {
				ep_id = (uint8_t)ep_item->valuedouble;
			}

			uint16_t transition = 10; /* 1 second default */
			cJSON *trans_item = cJSON_GetObjectItem(root, "transition");
			if (cJSON_IsNumber(trans_item)) {
				transition = (uint16_t)trans_item->valuedouble;
			}

			if (strcmp(cmd_str, "list") == 0) {
				handle_list();
			} else if (strcmp(cmd_str, "on") == 0) {
				cJSON *ieee = cJSON_GetObjectItem(root, "ieee");
				if (cJSON_IsString(ieee)) handle_on(ieee->valuestring, ep_id, corr_id);
			} else if (strcmp(cmd_str, "off") == 0) {
				cJSON *ieee = cJSON_GetObjectItem(root, "ieee");
				if (cJSON_IsString(ieee)) handle_off(ieee->valuestring, ep_id, corr_id);
			} else if (strcmp(cmd_str, "toggle") == 0) {
				cJSON *ieee = cJSON_GetObjectItem(root, "ieee");
				if (cJSON_IsString(ieee)) handle_toggle(ieee->valuestring, ep_id, corr_id);
			} else if (strcmp(cmd_str, "level") == 0) {
				cJSON *ieee = cJSON_GetObjectItem(root, "ieee");
				cJSON *lvl = cJSON_GetObjectItem(root, "level");
				if (cJSON_IsString(ieee) && cJSON_IsNumber(lvl)) {
					handle_level(ieee->valuestring, (uint8_t)lvl->valuedouble,
						     transition, ep_id, corr_id);
				}
			} else if (strcmp(cmd_str, "color") == 0) {
				cJSON *ieee = cJSON_GetObjectItem(root, "ieee");
				cJSON *hex = cJSON_GetObjectItem(root, "hex");
				cJSON *mode = cJSON_GetObjectItem(root, "mode");
				if (cJSON_IsString(ieee) && cJSON_IsString(hex) && cJSON_IsString(mode)) {
					handle_color(ieee->valuestring, hex->valuestring,
						     mode->valuestring, transition, ep_id, corr_id);
				}
			} else if (strcmp(cmd_str, "color_ct") == 0) {
				cJSON *ieee = cJSON_GetObjectItem(root, "ieee");
				cJSON *ct = cJSON_GetObjectItem(root, "ct");
				if (cJSON_IsString(ieee) && cJSON_IsNumber(ct)) {
					handle_color_ct(ieee->valuestring,
							(uint16_t)ct->valuedouble, transition, ep_id, corr_id);
				}
			} else if (strcmp(cmd_str, "read_attr") == 0) {
				cJSON *ieee = cJSON_GetObjectItem(root, "ieee");
				cJSON *cluster = cJSON_GetObjectItem(root, "cluster");
				cJSON *attr = cJSON_GetObjectItem(root, "attribute");
				if (cJSON_IsString(ieee) && cJSON_IsString(cluster) && cJSON_IsString(attr)) {
					handle_read_attr(ieee->valuestring, ep_id,
							 cluster->valuestring, attr->valuestring, corr_id);
				}
			} else if (strcmp(cmd_str, "ping") == 0) {
				cJSON *ieee = cJSON_GetObjectItem(root, "ieee");
				cJSON *corr = cJSON_GetObjectItem(root, "correlation_id");
				if (cJSON_IsString(ieee)) {
					handle_ping(ieee->valuestring,
						    cJSON_IsString(corr) ? corr->valuestring : NULL);
				}
			} else if (strcmp(cmd_str, "permit") == 0) {
				cJSON *dur = cJSON_GetObjectItem(root, "duration");
				if (cJSON_IsNumber(dur)) {
					handle_permit((uint8_t)dur->valuedouble);
				}
			} else {
				cJSON *err = cJSON_CreateObject();
				cJSON_AddStringToObject(err, "evt", "error");
				cJSON_AddStringToObject(err, "message", "unknown_cmd");
				send_json_line(err);
				cJSON_Delete(err);
			}

			cJSON_Delete(root);
		} else {
			vTaskDelay(pdMS_TO_TICKS(10));
		}
	}
}

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

esp_err_t serial_api_init(void)
{
	ESP_LOGI(TAG, "Starting USB Serial API task");
	s_stdout_mutex = xSemaphoreCreateMutex();
	if (s_stdout_mutex == NULL) {
		return ESP_ERR_NO_MEM;
	}
	memset(s_pending_pings, 0, sizeof(s_pending_pings));
	com_pipeline_subscribe(serial_event_handler, NULL);
	BaseType_t ret = xTaskCreate(serial_task, "serial_api", 4096, NULL, 5, NULL);
	if (ret != pdPASS) {
		vSemaphoreDelete(s_stdout_mutex);
		s_stdout_mutex = NULL;
		return ESP_ERR_NO_MEM;
	}
	return ESP_OK;
}
