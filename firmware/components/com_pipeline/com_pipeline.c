#include "com_pipeline.h"

#include <stdio.h>
#include <string.h>
#include <inttypes.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "esp_log.h"
#include "cJSON.h"

#define COM_PIPELINE_QUEUE_SIZE  16
#define COM_PIPELINE_TASK_STACK  4096
#define COM_PIPELINE_TASK_PRIO   5
#define COM_PIPELINE_EMIT_TIMEOUT_MS 100
#define COM_MAX_SUBSCRIBERS      4

static const char *TAG = "com_pipeline";

static QueueHandle_t s_com_queue = NULL;
static TaskHandle_t s_com_task = NULL;

typedef struct {
	com_pipeline_cb_t cb;
	void *user_data;
} subscriber_t;

static subscriber_t s_subscribers[COM_MAX_SUBSCRIBERS] = {0};

static void format_ieee_addr(char *buf, size_t buf_size, uint64_t ieee_addr)
{
	snprintf(buf, buf_size, "0x%016llx", (unsigned long long)ieee_addr);
}

static const char *device_type_to_str(uint8_t device_type)
{
	switch (device_type) {
		case 0: return "end_device";
		case 1: return "router";
		case 2: return "coordinator";
		default: return "unknown";
	}
}

static const char *power_source_to_str(uint8_t power_source)
{
	switch (power_source) {
		case 0: return "battery";
		case 1: return "mains";
		default: return "unknown";
	}
}

static cJSON *state_change_to_json(const com_state_change_t *change)
{
	cJSON *obj = cJSON_CreateObject();
	if (obj == NULL) {
		return NULL;
	}

	cJSON_AddStringToObject(obj, "cluster", change->cluster);
	cJSON_AddStringToObject(obj, "attribute", change->attribute);

	switch (change->type) {
		case 0:
			cJSON_AddBoolToObject(obj, "value", change->value.b_val);
			break;
		case 1:
			cJSON_AddNumberToObject(obj, "value", change->value.i_val);
			break;
		case 2:
			cJSON_AddNumberToObject(obj, "value", change->value.u_val);
			break;
		case 3:
			cJSON_AddNumberToObject(obj, "value", change->value.f_val);
			break;
		default:
			cJSON_AddNullToObject(obj, "value");
			break;
	}

	return obj;
}

static char *event_to_json(const com_event_t *event)
{
	cJSON *root = cJSON_CreateObject();
	if (root == NULL) {
		return NULL;
	}

	char ieee_str[32];

	switch (event->type) {
		case COM_EVT_CONNECTED:
			cJSON_AddStringToObject(root, "type", "connected");
			break;

		case COM_EVT_STATE_CHANGE: {
			cJSON_AddStringToObject(root, "type", "state_change");
			format_ieee_addr(ieee_str, sizeof(ieee_str), event->payload.state_change.ieee_addr);
			cJSON_AddStringToObject(root, "ieee", ieee_str);

			cJSON *changes = cJSON_CreateArray();
			if (changes != NULL) {
				for (uint8_t i = 0; i < event->payload.state_change.num_changes; i++) {
					cJSON *item = state_change_to_json(&event->payload.state_change.changes[i]);
					if (item != NULL) {
						cJSON_AddItemToArray(changes, item);
					}
				}
				cJSON_AddItemToObject(root, "changes", changes);
			}
			break;
		}

		case COM_EVT_DEVICE_JOINED: {
			cJSON_AddStringToObject(root, "type", "device_joined");
			format_ieee_addr(ieee_str, sizeof(ieee_str), event->payload.device_joined.ieee_addr);
			cJSON_AddStringToObject(root, "ieee", ieee_str);

			char net_addr_str[16];
			snprintf(net_addr_str, sizeof(net_addr_str), "0x%04X", event->payload.device_joined.network_addr);
			cJSON_AddStringToObject(root, "network_addr", net_addr_str);

			cJSON_AddStringToObject(root, "device_type",
						device_type_to_str(event->payload.device_joined.device_type));
			cJSON_AddStringToObject(root, "power_source",
						power_source_to_str(event->payload.device_joined.power_source));
			break;
		}

		case COM_EVT_DEVICE_LEFT: {
			cJSON_AddStringToObject(root, "type", "device_left");
			format_ieee_addr(ieee_str, sizeof(ieee_str), event->payload.device_left.ieee_addr);
			cJSON_AddStringToObject(root, "ieee", ieee_str);
			const char *reason = event->payload.device_left.reason ? event->payload.device_left.reason : "";
			cJSON_AddStringToObject(root, "reason", reason);
			break;
		}

		case COM_EVT_NETWORK_PERMIT_JOIN:
			cJSON_AddStringToObject(root, "type", "network_permit_join");
			cJSON_AddBoolToObject(root, "active", event->payload.permit_join.active);
			cJSON_AddNumberToObject(root, "duration_remaining", event->payload.permit_join.duration_remaining);
			break;

		case COM_EVT_COMMAND_FAILED:
			cJSON_AddStringToObject(root, "type", "command_failed");
			cJSON_AddStringToObject(root, "correlation_id", event->payload.command_failed.correlation_id);
			cJSON_AddStringToObject(root, "error", event->payload.command_failed.error);
			cJSON_AddStringToObject(root, "message", event->payload.command_failed.message);
			break;

		case COM_EVT_COMMAND_STATUS: {
			cJSON_AddStringToObject(root, "type", "command_status");
			cJSON_AddStringToObject(root, "correlation_id", event->payload.command_status.correlation_id);
			const char *status_str = "unknown";
			switch (event->payload.command_status.status) {
				case CMD_STATUS_PENDING:   status_str = "pending";   break;
				case CMD_STATUS_DELIVERED: status_str = "delivered"; break;
				case CMD_STATUS_COMPLETED: status_str = "completed"; break;
				case CMD_STATUS_FAILED:    status_str = "failed";    break;
				case CMD_STATUS_TIMEOUT:   status_str = "timeout";   break;
			}
			cJSON_AddStringToObject(root, "status", status_str);
			if (event->payload.command_status.reason[0] != '\0') {
				cJSON_AddStringToObject(root, "reason", event->payload.command_status.reason);
			}
			char ieee_str[32];
			format_ieee_addr(ieee_str, sizeof(ieee_str), event->payload.command_status.ieee_addr);
			cJSON_AddStringToObject(root, "ieee", ieee_str);
			char cluster_str[8];
			snprintf(cluster_str, sizeof(cluster_str), "0x%04X", event->payload.command_status.cluster_id);
			cJSON_AddStringToObject(root, "cluster", cluster_str);
			break;
		}

		default:
			cJSON_AddStringToObject(root, "type", "unknown");
			break;
	}

	char *json_str = cJSON_PrintUnformatted(root);
	cJSON_Delete(root);
	return json_str;
}

static void com_pipeline_task(void *pvParameters)
{
	(void)pvParameters;
	com_event_t event;

	while (1) {
		if (xQueueReceive(s_com_queue, &event, portMAX_DELAY) == pdTRUE) {
			for (int i = 0; i < COM_MAX_SUBSCRIBERS; i++) {
				if (s_subscribers[i].cb != NULL) {
					s_subscribers[i].cb(&event, s_subscribers[i].user_data);
				}
			}
		}
	}
}

esp_err_t com_pipeline_init(void)
{
	if (s_com_queue != NULL) {
		ESP_LOGW(TAG, "Already initialized");
		return ESP_ERR_INVALID_STATE;
	}

	s_com_queue = xQueueCreate(COM_PIPELINE_QUEUE_SIZE, sizeof(com_event_t));
	if (s_com_queue == NULL) {
		ESP_LOGE(TAG, "Failed to create queue");
		return ESP_FAIL;
	}

	BaseType_t ret = xTaskCreate(com_pipeline_task, "com_pipeline_task",
				     COM_PIPELINE_TASK_STACK, NULL,
				     COM_PIPELINE_TASK_PRIO, &s_com_task);
	if (ret != pdPASS) {
		vQueueDelete(s_com_queue);
		s_com_queue = NULL;
		ESP_LOGE(TAG, "Failed to create task");
		return ESP_FAIL;
	}

	ESP_LOGI(TAG, "Initialized");
	return ESP_OK;
}

esp_err_t com_pipeline_emit(const com_event_t *event)
{
	if (event == NULL) {
		return ESP_ERR_INVALID_ARG;
	}

	if (s_com_queue == NULL) {
		ESP_LOGE(TAG, "Not initialized");
		return ESP_ERR_INVALID_STATE;
	}

	if (xQueueSend(s_com_queue, event, pdMS_TO_TICKS(COM_PIPELINE_EMIT_TIMEOUT_MS)) != pdTRUE) {
		ESP_LOGW(TAG, "Queue full, event dropped");
		return ESP_FAIL;
	}

	return ESP_OK;
}

esp_err_t com_pipeline_subscribe(com_pipeline_cb_t cb, void *user_data)
{
	if (cb == NULL) {
		return ESP_ERR_INVALID_ARG;
	}
	for (int i = 0; i < COM_MAX_SUBSCRIBERS; i++) {
		if (s_subscribers[i].cb == NULL) {
			s_subscribers[i].cb = cb;
			s_subscribers[i].user_data = user_data;
			return ESP_OK;
		}
	}
	return ESP_ERR_NO_MEM;
}

char *com_pipeline_event_to_json(const com_event_t *event)
{
	return event_to_json(event);
}
