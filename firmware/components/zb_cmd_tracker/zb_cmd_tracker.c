#include "zb_cmd_tracker.h"

#include <string.h>
#include "zcl/esp_zigbee_zcl_common.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "com_pipeline.h"

/* Forward declaration - implemented by the zb_clusters component. */
esp_err_t zb_cluster_read_attr(uint64_t ieee, uint8_t ep_id, uint16_t cluster_id,
                               uint16_t attr_id, const char *corr_id);

#define TAG "zb_cmd_tracker"
#define ZB_CMD_TRACKER_SLOTS 32
#define ZB_CMD_TRACKER_CHECK_MS 1000
#define ZB_CMD_TRACKER_PROBE_MS 400
#define ZB_CMD_TRACKER_PROBE_RETRY_MS 1500

typedef struct {
	bool active;
	bool reserved;          /* slot reserved but not yet committed */
	char corr_id[COM_CORR_ID_LEN];
	uint64_t ieee;
	uint8_t endpoint;
	uint16_t cluster_id;
	uint16_t attr_id;       /* 0xFFFF = any attr */
	uint16_t probe_attr_id; /* attribute used for read-after-write probe */
	bool check_value;
	uint32_t expected_val;
	int64_t deadline_ms;
	esp_timer_handle_t probe_timer;
	uint32_t nonce;
	uint32_t probe_nonce;
} slot_t;

static slot_t s_slots[ZB_CMD_TRACKER_SLOTS];
static SemaphoreHandle_t s_mutex = NULL;
static uint32_t s_next_nonce = 1;

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

static void clear_probe_timer_locked(int slot)
{
	if (s_slots[slot].probe_timer != NULL) {
		esp_timer_stop(s_slots[slot].probe_timer);
		esp_timer_delete(s_slots[slot].probe_timer);
		s_slots[slot].probe_timer = NULL;
		s_slots[slot].probe_nonce = 0;
	}
}

static void probe_timer_cb(void *arg)
{
	slot_t *slot = (slot_t *)arg;

	xSemaphoreTake(s_mutex, portMAX_DELAY);
	if (!slot->active || slot->reserved || slot->nonce != slot->probe_nonce) {
		xSemaphoreGive(s_mutex);
		return;
	}
	uint64_t ieee = slot->ieee;
	uint8_t endpoint = slot->endpoint;
	uint16_t cluster_id = slot->cluster_id;
	uint16_t attr_id = slot->probe_attr_id;

	/*
	 * Keep probing until the slot resolves or expires. Dimmers ramp to the
	 * target and the device reporting engine may swallow the settled value
	 * (min reporting interval), so this read-back is what guarantees the
	 * final level reaches the host instead of a mid-ramp intermediate one.
	 * Re-arm before the read: a report that resolves the slot while the
	 * read is in flight simply makes the next callback a no-op.
	 */
	if (slot->probe_timer != NULL) {
		esp_err_t arm_err = esp_timer_start_once(
			slot->probe_timer,
			(uint64_t)ZB_CMD_TRACKER_PROBE_RETRY_MS * 1000ULL);
		if (arm_err != ESP_OK) {
			ESP_LOGW(TAG, "Failed to re-arm probe timer: %s",
				 esp_err_to_name(arm_err));
		}
	}
	xSemaphoreGive(s_mutex);

	esp_err_t err = zb_cluster_read_attr(ieee, endpoint, cluster_id, attr_id,
					     "probe");
	if (err != ESP_OK) {
		ESP_LOGW(TAG, "Probe read attr failed: %s", esp_err_to_name(err));
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
				clear_probe_timer_locked(i);
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
                          uint8_t endpoint, uint16_t cluster_id, uint16_t attr_id,
                          bool is_write, bool check_value, uint32_t expected_val,
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
	s_slots[slot].endpoint = endpoint;
	s_slots[slot].cluster_id = cluster_id;
	s_slots[slot].attr_id = attr_id;
	if (attr_id != 0xFFFF) {
		s_slots[slot].probe_attr_id = attr_id;
	} else {
		/* For "any attribute" matches (e.g. toggle) pick a sensible default
		 * to read after writing. */
		switch (cluster_id) {
		case 0x0008:
			s_slots[slot].probe_attr_id = 0x0000; /* CurrentLevel */
			break;
		case 0x0300:
			s_slots[slot].probe_attr_id = 0x0008; /* ColorMode */
			break;
		case 0x0006:
		default:
			s_slots[slot].probe_attr_id = 0x0000; /* OnOff */
			break;
		}
	}
	s_slots[slot].check_value = check_value;
	s_slots[slot].expected_val = expected_val;
	s_slots[slot].deadline_ms = (esp_timer_get_time() / 1000) + timeout_ms;
	s_slots[slot].reserved = false;
	s_slots[slot].nonce = s_next_nonce++;
	if (s_next_nonce == 0) {
		s_next_nonce = 1;
	}

	if (is_write) {
		esp_timer_create_args_t timer_args = {
			.callback = probe_timer_cb,
			.arg = &s_slots[slot],
			.name = "cmd_probe",
		};
		s_slots[slot].probe_nonce = s_slots[slot].nonce;
		if (esp_timer_create(&timer_args,
				     &s_slots[slot].probe_timer) != ESP_OK ||
		    esp_timer_start_once(s_slots[slot].probe_timer,
					 (uint64_t)ZB_CMD_TRACKER_PROBE_MS * 1000ULL) != ESP_OK) {
			ESP_LOGW(TAG, "Failed to start probe timer for slot %d", slot);
			if (s_slots[slot].probe_timer != NULL) {
				esp_timer_delete(s_slots[slot].probe_timer);
				s_slots[slot].probe_timer = NULL;
			}
			s_slots[slot].probe_nonce = 0;
		}
	}
}

static void release_locked(int slot)
{
	if (slot < 0 || slot >= ZB_CMD_TRACKER_SLOTS) {
		return;
	}
	if (s_slots[slot].active && s_slots[slot].reserved) {
		clear_probe_timer_locked(slot);
		s_slots[slot].active = false;
		s_slots[slot].reserved = false;
	}
}

esp_err_t zb_cmd_tracker_register(const char *corr_id, uint64_t ieee,
                                  uint8_t endpoint, uint16_t cluster_id,
                                  uint16_t attr_id, bool is_write,
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
	commit_locked(slot, corr_id, ieee, endpoint, cluster_id, attr_id,
		      is_write, check_value, expected_val, timeout_ms);
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
                           uint8_t endpoint, uint16_t cluster_id,
                           uint16_t attr_id, bool is_write, bool check_value,
                           uint32_t expected_val, uint32_t timeout_ms)
{
	if (!corr_id || !s_mutex) {
		return;
	}
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	commit_locked(slot, corr_id, ieee, endpoint, cluster_id, attr_id,
		      is_write, check_value, expected_val, timeout_ms);
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
		clear_probe_timer_locked(i);
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
			clear_probe_timer_locked(i);
			s_slots[i].active = false;
		}
	}
	xSemaphoreGive(s_mutex);
}
