#include "zb_cmd_tracker.h"

#include <string.h>
#include "zcl/esp_zigbee_zcl_common.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "com_pipeline.h"

#define TAG "zb_cmd_tracker"
#define ZB_CMD_TRACKER_SLOTS 32
#define ZB_CMD_TRACKER_CHECK_MS 1000

typedef struct {
	bool active;
	bool reserved;          /* slot reserved but not yet committed */
	char corr_id[COM_CORR_ID_LEN];
	uint64_t ieee;
	uint16_t cluster_id;
	uint16_t attr_id;       /* 0xFFFF = any attr */
	bool check_value;
	uint32_t expected_val;
	int64_t deadline_ms;
} slot_t;

static slot_t s_slots[ZB_CMD_TRACKER_SLOTS];
static SemaphoreHandle_t s_mutex = NULL;

static void emit_status(const char *corr_id, com_cmd_status_t status, const char *reason,
			uint64_t ieee, uint16_t cluster)
{
	com_event_t evt = { .type = COM_EVT_COMMAND_STATUS };
	strncpy(evt.payload.command_status.correlation_id, corr_id, COM_CORR_ID_LEN - 1);
	evt.payload.command_status.correlation_id[COM_CORR_ID_LEN - 1] = '\0';
	evt.payload.command_status.status = status;
	if (reason) {
		strncpy(evt.payload.command_status.reason, reason,
			sizeof(evt.payload.command_status.reason) - 1);
	} else {
		evt.payload.command_status.reason[0] = '\0';
	}
	evt.payload.command_status.ieee_addr = ieee;
	evt.payload.command_status.cluster_id = cluster;
	com_pipeline_emit(&evt);
}

static uint32_t extract_u32(const void *value, uint8_t type)
{
	if (value == NULL) {
		return 0;
	}
	switch (type) {
	case 0:
		return *(const uint8_t *)value;
	case 1:
		return *(const uint16_t *)value;
	case 2:
		return *(const uint32_t *)value;
	case 4:
		return *(const bool *)value ? 1U : 0U;
	case 5:
		return (uint32_t)(*(const int16_t *)value);
	default:
		return 0;
	}
}

static void tracker_task(void *arg)
{
	(void)arg;
	while (1) {
		vTaskDelay(pdMS_TO_TICKS(ZB_CMD_TRACKER_CHECK_MS));
		int64_t now = esp_timer_get_time() / 1000;
		xSemaphoreTake(s_mutex, portMAX_DELAY);
		for (int i = 0; i < ZB_CMD_TRACKER_SLOTS; i++) {
			if (s_slots[i].active && !s_slots[i].reserved && now >= s_slots[i].deadline_ms) {
				emit_status(s_slots[i].corr_id, CMD_STATUS_TIMEOUT, "no_response",
					    s_slots[i].ieee, s_slots[i].cluster_id);
				s_slots[i].active = false;
			}
		}
		xSemaphoreGive(s_mutex);
	}
}

esp_err_t zb_cmd_tracker_init(void)
{
	s_mutex = xSemaphoreCreateMutex();
	if (!s_mutex) {
		return ESP_ERR_NO_MEM;
	}
	memset(s_slots, 0, sizeof(s_slots));
	BaseType_t ret = xTaskCreate(tracker_task, "zb_cmd_tracker", 4096, NULL, 5, NULL);
	if (ret != pdPASS) {
		vSemaphoreDelete(s_mutex);
		s_mutex = NULL;
		return ESP_ERR_NO_MEM;
	}
	return ESP_OK;
}

/* Internal helpers - caller must hold s_mutex */
static int reserve_locked(void)
{
	for (int i = 0; i < ZB_CMD_TRACKER_SLOTS; i++) {
		if (!s_slots[i].active) {
			memset(&s_slots[i], 0, sizeof(s_slots[i]));
			s_slots[i].active = true;
			s_slots[i].reserved = true;
			return i;
		}
	}
	return -1;
}

static void commit_locked(int slot, const char *corr_id, uint64_t ieee,
                          uint16_t cluster_id, uint16_t attr_id,
                          bool check_value, uint32_t expected_val,
                          uint32_t timeout_ms)
{
	if (slot < 0 || slot >= ZB_CMD_TRACKER_SLOTS) {
		return;
	}
	if (!s_slots[slot].active || !s_slots[slot].reserved) {
		return;
	}
	strncpy(s_slots[slot].corr_id, corr_id, COM_CORR_ID_LEN - 1);
	s_slots[slot].corr_id[COM_CORR_ID_LEN - 1] = '\0';
	s_slots[slot].ieee = ieee;
	s_slots[slot].cluster_id = cluster_id;
	s_slots[slot].attr_id = attr_id;
	s_slots[slot].check_value = check_value;
	s_slots[slot].expected_val = expected_val;
	s_slots[slot].deadline_ms = (esp_timer_get_time() / 1000) + timeout_ms;
	s_slots[slot].reserved = false;
}

static void release_locked(int slot)
{
	if (slot < 0 || slot >= ZB_CMD_TRACKER_SLOTS) {
		return;
	}
	if (s_slots[slot].active && s_slots[slot].reserved) {
		s_slots[slot].active = false;
		s_slots[slot].reserved = false;
	}
}

esp_err_t zb_cmd_tracker_register(const char *corr_id, uint64_t ieee,
                                  uint16_t cluster_id, uint16_t attr_id,
                                  bool check_value, uint32_t expected_val,
                                  uint32_t timeout_ms)
{
	if (!corr_id || !s_mutex) {
		return ESP_ERR_INVALID_STATE;
	}
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	int slot = reserve_locked();
	if (slot < 0) {
		xSemaphoreGive(s_mutex);
		return ESP_ERR_NO_MEM;
	}
	commit_locked(slot, corr_id, ieee, cluster_id, attr_id,
		      check_value, expected_val, timeout_ms);
	xSemaphoreGive(s_mutex);
	return ESP_OK;
}

int zb_cmd_tracker_reserve(void)
{
	if (!s_mutex) {
		return -1;
	}
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	int slot = reserve_locked();
	xSemaphoreGive(s_mutex);
	return slot;
}

void zb_cmd_tracker_commit(int slot, const char *corr_id, uint64_t ieee,
                           uint16_t cluster_id, uint16_t attr_id,
                           bool check_value, uint32_t expected_val,
                           uint32_t timeout_ms)
{
	if (!corr_id || !s_mutex) {
		return;
	}
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	commit_locked(slot, corr_id, ieee, cluster_id, attr_id,
		      check_value, expected_val, timeout_ms);
	xSemaphoreGive(s_mutex);
}

void zb_cmd_tracker_release(int slot)
{
	if (!s_mutex) {
		return;
	}
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	release_locked(slot);
	xSemaphoreGive(s_mutex);
}

void zb_cmd_tracker_on_report(uint64_t ieee, uint16_t cluster_id, uint16_t attr_id,
                              const void *value, uint8_t type)
{
	if (!s_mutex) {
		return;
	}
	uint32_t val = extract_u32(value, type);
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	for (int i = 0; i < ZB_CMD_TRACKER_SLOTS; i++) {
		if (!s_slots[i].active || s_slots[i].reserved) {
			continue;
		}
		if (s_slots[i].ieee != ieee) {
			continue;
		}
		if (s_slots[i].cluster_id != cluster_id) {
			continue;
		}
		if (s_slots[i].attr_id != 0xFFFF && s_slots[i].attr_id != attr_id) {
			continue;
		}
		if (s_slots[i].check_value && val != s_slots[i].expected_val) {
			continue;
		}
		emit_status(s_slots[i].corr_id, CMD_STATUS_COMPLETED, NULL,
			    ieee, cluster_id);
		s_slots[i].active = false;
	}
	xSemaphoreGive(s_mutex);
}

void zb_cmd_tracker_on_default_resp(uint64_t ieee, uint16_t cluster_id,
                                    uint8_t cmd_id, uint8_t zcl_status)
{
	(void)cmd_id;
	if (!s_mutex) {
		return;
	}
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	for (int i = 0; i < ZB_CMD_TRACKER_SLOTS; i++) {
		if (!s_slots[i].active || s_slots[i].reserved) {
			continue;
		}
		if (s_slots[i].ieee != ieee) {
			continue;
		}
		if (s_slots[i].cluster_id != cluster_id) {
			continue;
		}
		if (zcl_status == ESP_ZB_ZCL_STATUS_SUCCESS) {
			emit_status(s_slots[i].corr_id, CMD_STATUS_DELIVERED,
				    "default_resp_ok", ieee, cluster_id);
		} else {
			emit_status(s_slots[i].corr_id, CMD_STATUS_FAILED,
				    "zcl_error", ieee, cluster_id);
			s_slots[i].active = false;
		}
	}
	xSemaphoreGive(s_mutex);
}
