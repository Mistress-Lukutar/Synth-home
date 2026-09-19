#include "com_pipeline.h"

#include <stdio.h>
#include <string.h>
#include <inttypes.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "esp_timer.h"

#include "esp_log.h"
#include "cJSON.h"
#include "hub_stats.h"

/*
 * Queue must absorb report bursts without stalling the Zigbee stack task
 * (emit is non-blocking); 32 was too shallow during a refresh storm.
 */
#define COM_PIPELINE_QUEUE_SIZE  128
#define COM_PIPELINE_TASK_STACK  4096
#define COM_PIPELINE_TASK_PRIO   5
#define COM_MAX_SUBSCRIBERS      4

/* Per-device state_change coalescing window (see com_pipeline_emit_state_change). */
#define COM_STATE_COALESCE_MS    50
#define COM_COALESCE_SLOTS       32

static const char *TAG = "com_pipeline";

static QueueHandle_t s_com_queue = NULL;
static TaskHandle_t s_com_task = NULL;

typedef struct {
	com_pipeline_cb_t cb;
	void *user_data;
} subscriber_t;

static subscriber_t s_subscribers[COM_MAX_SUBSCRIBERS] = {0};

/* -------------------------------------------------------------------------- */
/* State-change coalescing                                                    */
/* -------------------------------------------------------------------------- */

typedef struct {
	uint64_t           ieee_addr;
	com_state_change_t changes[COM_MAX_CHANGES];
	uint8_t            num_changes;
	esp_timer_handle_t flush_timer;
	bool               timer_armed;
} coalesce_slot_t;

static coalesce_slot_t s_coalesce[COM_COALESCE_SLOTS];
static SemaphoreHandle_t s_coalesce_mutex = NULL;

static void coalesce_flush_locked(coalesce_slot_t *slot)
{
	if (slot->num_changes == 0) {
		return;
	}
	if (slot->timer_armed && slot->flush_timer != NULL) {
		esp_timer_stop(slot->flush_timer);
		slot->timer_armed = false;
	}

	com_event_t evt = { .type = COM_EVT_STATE_CHANGE };
	evt.payload.state_change.ieee_addr = slot->ieee_addr;
	evt.payload.state_change.num_changes = slot->num_changes;
	for (uint8_t i = 0; i < slot->num_changes; i++) {
		evt.payload.state_change.changes[i] = slot->changes[i];
	}
	if (slot->num_changes > 1) {
		hub_stats_add(HUB_STATS_STATE_COALESCED, slot->num_changes - 1);
	}
	slot->num_changes = 0;

	com_pipeline_emit(&evt);
}

static void coalesce_flush_timer_cb(void *arg)
{
	coalesce_slot_t *slot = (coalesce_slot_t *)arg;
	if (s_coalesce_mutex == NULL) {
		return;
	}
	xSemaphoreTake(s_coalesce_mutex, portMAX_DELAY);
	coalesce_flush_locked(slot);
	xSemaphoreGive(s_coalesce_mutex);
}

void com_pipeline_emit_state_change(uint64_t ieee, const com_state_change_t *change)
{
	if (s_coalesce_mutex == NULL || change == NULL) {
		return;
	}

	xSemaphoreTake(s_coalesce_mutex, portMAX_DELAY);

	coalesce_slot_t *slot = NULL;
	for (int i = 0; i < COM_COALESCE_SLOTS; i++) {
		if (s_coalesce[i].num_changes > 0 && s_coalesce[i].ieee_addr == ieee) {
			slot = &s_coalesce[i];
			break;
		}
	}
	if (slot == NULL) {
		for (int i = 0; i < COM_COALESCE_SLOTS; i++) {
			if (s_coalesce[i].num_changes == 0) {
				slot = &s_coalesce[i];
				break;
			}
		}
	}
	if (slot == NULL) {
		/* No free slot: fall back to an uncoalesced event. */
		com_event_t evt = { .type = COM_EVT_STATE_CHANGE };
		evt.payload.state_change.ieee_addr = ieee;
		evt.payload.state_change.num_changes = 1;
		evt.payload.state_change.changes[0] = *change;
		xSemaphoreGive(s_coalesce_mutex);
		com_pipeline_emit(&evt);
		return;
	}

	slot->ieee_addr = ieee;
	slot->changes[slot->num_changes++] = *change;
	if (slot->num_changes >= COM_MAX_CHANGES) {
		coalesce_flush_locked(slot);
		xSemaphoreGive(s_coalesce_mutex);
		return;
	}

	if (!slot->timer_armed && slot->flush_timer != NULL) {
		esp_timer_start_once(slot->flush_timer,
				     (uint64_t)COM_STATE_COALESCE_MS * 1000ULL);
		slot->timer_armed = true;
	}
	xSemaphoreGive(s_coalesce_mutex);
}

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

	s_coalesce_mutex = xSemaphoreCreateMutex();
	if (s_coalesce_mutex == NULL) {
		vQueueDelete(s_com_queue);
		s_com_queue = NULL;
		return ESP_FAIL;
	}

	for (int i = 0; i < COM_COALESCE_SLOTS; i++) {
		esp_timer_create_args_t timer_args = {
			.callback = coalesce_flush_timer_cb,
			.arg = &s_coalesce[i],
			.name = "com_coalesce",
		};
		if (esp_timer_create(&timer_args, &s_coalesce[i].flush_timer) != ESP_OK) {
			s_coalesce[i].flush_timer = NULL;
		}
	}

	BaseType_t ret = xTaskCreate(com_pipeline_task, "com_pipeline_task",
				     COM_PIPELINE_TASK_STACK, NULL,
				     COM_PIPELINE_TASK_PRIO, &s_com_task);
	if (ret != pdPASS) {
		vQueueDelete(s_com_queue);
		s_com_queue = NULL;
		vSemaphoreDelete(s_coalesce_mutex);
		s_coalesce_mutex = NULL;
		ESP_LOGE(TAG, "Failed to create task");
		return ESP_FAIL;
	}

	ESP_LOGI(TAG, "Initialized (queue depth %d)", COM_PIPELINE_QUEUE_SIZE);
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

	/*
	 * Never block: emits come from the Zigbee stack task where a 100 ms
	 * queue wait would stall the whole radio stack and snowball lock
	 * contention into the command senders.
	 */
	if (xQueueSend(s_com_queue, event, 0) != pdTRUE) {
		ESP_LOGW(TAG, "Queue full, event dropped");
		hub_stats_inc(HUB_STATS_QUEUE_FULL_DROPS);
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
