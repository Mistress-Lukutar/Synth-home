#include "zb_cmd_tracker.h"

#include <string.h>
#include "zcl/esp_zigbee_zcl_common.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "com_pipeline.h"
#include "hub_stats.h"

/* Forward declaration - implemented by the zb_clusters component. */
esp_err_t zb_cluster_read_attr(uint64_t ieee, uint8_t ep_id, uint16_t cluster_id,
                               uint16_t attr_id, const char *corr_id);

#define TAG "zb_cmd_tracker"
#define ZB_CMD_TRACKER_SLOTS 32
#define ZB_CMD_TRACKER_CHECK_MS 1000
/*
 * First probe 1 s after the send: an immediate report from the device
 * resolves the slot before the probe fires, so only unresolved commands
 * pay for a read-back.
 */
#define ZB_CMD_TRACKER_PROBE_MS 1000
#define ZB_CMD_TRACKER_PROBE_RETRY_MS 1500
/* Hard cap of read-back probes per command (congestion guard). */
#define ZB_CMD_TRACKER_PROBE_MAX 3
/* Emissions buffered per tracker pass while the mutex is held. */
#define ZB_CMD_TRACKER_EMIT_MAX 8

typedef struct {
	bool active;
	bool reserved;          /* slot reserved but not yet committed */
	bool delivered;         /* ZCL Default Response SUCCESS seen */
	uint8_t probe_count;    /* read-back probes already sent */
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

/* Status emission buffered while the tracker mutex is held; sent after unlock. */
typedef struct {
	char corr_id[COM_CORR_ID_LEN];
	com_cmd_status_t status;
	char reason[32];
	uint64_t ieee;
	uint16_t cluster_id;
} pending_emit_t;

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

static void buffer_emit(pending_emit_t *out, int *out_len, const slot_t *slot,
			com_cmd_status_t status, const char *reason)
{
	if (*out_len >= ZB_CMD_TRACKER_EMIT_MAX) {
		/* Overrun of the local buffer (cannot happen with one command
		 * per device in flight): fall back to emitting directly. */
		emit_status(slot->corr_id, status, reason, slot->ieee, slot->cluster_id);
		return;
	}
	pending_emit_t *dst = &out[(*out_len)++];
	strncpy(dst->corr_id, slot->corr_id, COM_CORR_ID_LEN - 1);
	dst->corr_id[COM_CORR_ID_LEN - 1] = '\0';
	dst->status = status;
	if (reason) {
		strncpy(dst->reason, reason, sizeof(dst->reason) - 1);
		dst->reason[sizeof(dst->reason) - 1] = '\0';
	} else {
		dst->reason[0] = '\0';
	}
	dst->ieee = slot->ieee;
	dst->cluster_id = slot->cluster_id;
}

static void flush_emits(pending_emit_t *emits, int len)
{
	for (int i = 0; i < len; i++) {
		emit_status(emits[i].corr_id, emits[i].status, emits[i].reason,
			    emits[i].ieee, emits[i].cluster_id);
	}
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

	/*
	 * Probe caps (congestion guard): at most PROBE_MAX reads per command,
	 * and after a ZCL Default Response DELIVERED at most one confirming
	 * read. Without the caps a 9-command scene added 50-80 extra on-air
	 * reads while the refresh storm was already saturating the bulbs.
	 */
	if (slot->probe_count >= ZB_CMD_TRACKER_PROBE_MAX ||
	    (slot->delivered && slot->probe_count >= 1)) {
		clear_probe_timer_locked(slot - s_slots);
		xSemaphoreGive(s_mutex);
		return;
	}

	uint64_t ieee = slot->ieee;
	uint8_t endpoint = slot->endpoint;
	uint16_t cluster_id = slot->cluster_id;
	uint16_t attr_id = slot->probe_attr_id;
	slot->probe_count++;

	/*
	 * Keep probing until the slot resolves or expires. Dimmers ramp to the
	 * target and the device reporting engine may swallow the settled value
	 * (min reporting interval), so this read-back is what guarantees the
	 * final level reaches the host instead of a mid-ramp intermediate one.
	 * Re-arm before the read: a report that resolves the slot while the
	 * read is in flight simply makes the next callback a no-op.
	 */
	if (slot->probe_timer != NULL) {
		bool rearm = slot->probe_count < ZB_CMD_TRACKER_PROBE_MAX &&
			     !(slot->delivered && slot->probe_count >= 1);
		if (rearm) {
			esp_err_t arm_err = esp_timer_start_once(
				slot->probe_timer,
				(uint64_t)ZB_CMD_TRACKER_PROBE_RETRY_MS * 1000ULL);
			if (arm_err != ESP_OK) {
				ESP_LOGW(TAG, "Failed to re-arm probe timer: %s",
					 esp_err_to_name(arm_err));
			}
		}
	}
	xSemaphoreGive(s_mutex);

	esp_err_t err = zb_cluster_read_attr(ieee, endpoint, cluster_id, attr_id,
					     "probe");
	hub_stats_inc(HUB_STATS_PROBE_READS);
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
		pending_emit_t emits[ZB_CMD_TRACKER_EMIT_MAX];
		int emit_len = 0;
		xSemaphoreTake(s_mutex, portMAX_DELAY);
		for (int i = 0; i < ZB_CMD_TRACKER_SLOTS; i++) {
			if (s_slots[i].active && !s_slots[i].reserved && now >= s_slots[i].deadline_ms) {
				buffer_emit(emits, &emit_len, &s_slots[i],
					    CMD_STATUS_TIMEOUT, "no_response");
				clear_probe_timer_locked(i);
				s_slots[i].active = false;
			}
		}
		xSemaphoreGive(s_mutex);
		flush_emits(emits, emit_len);
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
	pending_emit_t emits[ZB_CMD_TRACKER_EMIT_MAX];
	int emit_len = 0;
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
		buffer_emit(emits, &emit_len, &s_slots[i], CMD_STATUS_COMPLETED, NULL);
		clear_probe_timer_locked(i);
		s_slots[i].active = false;
	}
	xSemaphoreGive(s_mutex);
	flush_emits(emits, emit_len);
}

void zb_cmd_tracker_on_default_resp(uint64_t ieee, uint16_t cluster_id,
                                    uint8_t cmd_id, uint8_t zcl_status)
{
	(void)cmd_id;
	if (!s_mutex) {
		return;
	}
	pending_emit_t emits[ZB_CMD_TRACKER_EMIT_MAX];
	int emit_len = 0;
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
			s_slots[i].delivered = true;
			buffer_emit(emits, &emit_len, &s_slots[i],
				    CMD_STATUS_DELIVERED, "default_resp_ok");
		} else {
			buffer_emit(emits, &emit_len, &s_slots[i],
				    CMD_STATUS_FAILED, "zcl_error");
			clear_probe_timer_locked(i);
			s_slots[i].active = false;
		}
	}
	xSemaphoreGive(s_mutex);
	flush_emits(emits, emit_len);
}
