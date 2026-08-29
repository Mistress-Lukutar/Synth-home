#include "zb_device_mgr.h"
#include "zb_clusters.h"

#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs_storage.h"
#include "nvs.h"
#include "com_pipeline.h"

#include "esp_zigbee_core.h"
#include "zdo/esp_zigbee_zdo_command.h"
#include "zcl/esp_zigbee_zcl_command.h"
#include "zcl/esp_zigbee_zcl_common.h"

static const char *TAG = "zb_device_mgr";

static zb_device_record_t s_device_table[ZB_MAX_DEVICES];
static SemaphoreHandle_t  s_mutex = NULL;
static SemaphoreHandle_t  s_interview_mutex = NULL;

typedef struct {
	uint64_t ieee_addr;
	uint16_t short_addr;
	uint8_t pending_endpoint;
} zb_interview_ctx_t;

static zb_interview_ctx_t s_interview_ctx = {0};

#define ZB_LIVENESS_NS  "zb_liveness"
#define ZB_LIVENESS_KEY "liveness_table"

typedef struct {
	bool    online;
	int64_t last_seen_ms;
} zb_liveness_entry_t;

static zb_liveness_entry_t s_liveness_table[ZB_MAX_DEVICES];

static int s_find_device_index(uint64_t ieee)
{
	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr == ieee) {
			return i;
		}
	}
	return -1;
}

static void s_save_liveness(void)
{
	nvs_storage_set_blob(ZB_LIVENESS_NS, ZB_LIVENESS_KEY,
			     s_liveness_table, sizeof(s_liveness_table));
}

static void s_load_liveness(void)
{
	size_t    len = sizeof(s_liveness_table);
	esp_err_t err = nvs_storage_get_blob(ZB_LIVENESS_NS, ZB_LIVENESS_KEY,
					     s_liveness_table, &len);
	if (err == ESP_ERR_NVS_NOT_FOUND) {
		memset(s_liveness_table, 0, sizeof(s_liveness_table));
	} else if (err != ESP_OK || len != sizeof(s_liveness_table)) {
		ESP_LOGW(TAG, "Liveness table size mismatch or read error, resetting");
		memset(s_liveness_table, 0, sizeof(s_liveness_table));
	}
}

static void zb_device_mgr_active_ep_cb(esp_zb_zdp_status_t zdo_status, uint8_t ep_count, uint8_t *ep_id_list, void *user_ctx);
static void zb_device_mgr_simple_desc_cb(esp_zb_zdp_status_t zdo_status, esp_zb_af_simple_desc_1_1_t *simple_desc, void *user_ctx);

/* -------------------------------------------------------------------------- */
/* Internal helpers                                                           */
/* -------------------------------------------------------------------------- */

static void s_configure_cluster_reports(uint16_t network_addr, uint64_t ieee,
                                        uint8_t ep_id, uint16_t cluster_id)
{
	switch (cluster_id) {
	case 0x0006:
		zb_cluster_send_bind_req(network_addr, ieee, ep_id, cluster_id);
		zb_cluster_send_configure_reporting(network_addr, ep_id, cluster_id,
						    0x0000,
						    ESP_ZB_ZCL_ATTR_TYPE_BOOL);
		break;
	case 0x0008:
		zb_cluster_send_bind_req(network_addr, ieee, ep_id, cluster_id);
		zb_cluster_send_configure_reporting(network_addr, ep_id, cluster_id,
						    0x0000,
						    ESP_ZB_ZCL_ATTR_TYPE_U8);
		break;
	case 0x0300: {
		zb_cluster_send_bind_req(network_addr, ieee, ep_id, cluster_id);
		static const struct {
			uint16_t attr_id;
			uint8_t  attr_type;
		} color_attrs[] = {
			{0x0000, ESP_ZB_ZCL_ATTR_TYPE_U8},
			{0x0001, ESP_ZB_ZCL_ATTR_TYPE_U8},
			{0x0003, ESP_ZB_ZCL_ATTR_TYPE_U16},
			{0x0004, ESP_ZB_ZCL_ATTR_TYPE_U16},
			{0x0007, ESP_ZB_ZCL_ATTR_TYPE_U16},
			{0x0008, ESP_ZB_ZCL_ATTR_TYPE_U8},
		};
		for (size_t i = 0; i < sizeof(color_attrs) / sizeof(color_attrs[0]); i++) {
			zb_cluster_send_configure_reporting(network_addr, ep_id, cluster_id,
						    color_attrs[i].attr_id,
						    color_attrs[i].attr_type);
		}
		break;
	}
	default:
		break;
	}
}

static esp_err_t s_save_table(void)
{
	size_t      len = sizeof(s_device_table);
	esp_err_t   err = nvs_storage_set_blob("zb_devs", "device_table",
						 s_device_table, len);
	if (err != ESP_OK) {
		ESP_LOGE(TAG, "Failed to save device table: %s", esp_err_to_name(err));
	}
	return err;
}

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

esp_err_t zb_device_mgr_init(void)
{
	if (s_mutex != NULL) {
		return ESP_OK;
	}

	s_mutex = xSemaphoreCreateMutex();
	s_interview_mutex = xSemaphoreCreateMutex();
	if (s_mutex == NULL || s_interview_mutex == NULL) {
		return ESP_ERR_NO_MEM;
	}

	memset(s_device_table, 0, sizeof(s_device_table));
	esp_err_t err = zb_device_mgr_load();
	s_load_liveness();

	int64_t now_ms = esp_timer_get_time() / 1000;
	/* Ensure every loaded device has a liveness entry */
	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr != 0ULL) {
			if (s_liveness_table[i].last_seen_ms == 0) {
				s_liveness_table[i].online = true;
				s_liveness_table[i].last_seen_ms = now_ms;
			}
		}
	}

	/* Re-interview devices that were saved without endpoints */
	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr != 0ULL && s_device_table[i].endpoint_count == 0) {
			ESP_LOGI(TAG, "Re-starting interview for saved device 0x%016llX",
				 s_device_table[i].ieee_addr);
			zb_device_mgr_start_interview(s_device_table[i].ieee_addr);
		}
	}

	return err;
}

esp_err_t zb_device_mgr_add(uint64_t ieee, uint16_t nwk_addr,
                            uint8_t dev_type, uint8_t power_source)
{
	if (ieee == 0ULL) {
		return ESP_ERR_INVALID_ARG;
	}

	xSemaphoreTake(s_mutex, portMAX_DELAY);

	int free_idx = -1;
	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr == ieee) {
			s_device_table[i].network_addr = nwk_addr;
			s_device_table[i].device_type  = dev_type;
			s_device_table[i].power_source = power_source;
			s_liveness_table[i].online       = true;
			s_liveness_table[i].last_seen_ms = esp_timer_get_time() / 1000;
			esp_err_t err = s_save_table();
			s_save_liveness();
			xSemaphoreGive(s_mutex);
			return err;
		}
		if (free_idx == -1 && s_device_table[i].ieee_addr == 0ULL) {
			free_idx = i;
		}
	}

	if (free_idx == -1) {
		xSemaphoreGive(s_mutex);
		return ESP_ERR_NO_MEM;
	}

	memset(&s_device_table[free_idx], 0, sizeof(zb_device_record_t));
	s_device_table[free_idx].ieee_addr    = ieee;
	s_device_table[free_idx].network_addr = nwk_addr;
	s_device_table[free_idx].device_type  = dev_type;
	s_device_table[free_idx].power_source = power_source;

	s_liveness_table[free_idx].online        = true;
	s_liveness_table[free_idx].last_seen_ms  = esp_timer_get_time() / 1000;

	esp_err_t err = s_save_table();
	s_save_liveness();
	xSemaphoreGive(s_mutex);
	return err;
}

esp_err_t zb_device_mgr_remove(uint64_t ieee)
{
	xSemaphoreTake(s_mutex, portMAX_DELAY);

	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr == ieee) {
			memset(&s_device_table[i], 0, sizeof(zb_device_record_t));
			memset(&s_liveness_table[i], 0, sizeof(zb_liveness_entry_t));
			esp_err_t err = s_save_table();
			s_save_liveness();
			xSemaphoreGive(s_mutex);
			return err;
		}
	}

	xSemaphoreGive(s_mutex);
	return ESP_ERR_NOT_FOUND;
}

const zb_device_record_t *zb_device_mgr_get(uint64_t ieee)
{
	xSemaphoreTake(s_mutex, portMAX_DELAY);

	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr == ieee) {
			xSemaphoreGive(s_mutex);
			return &s_device_table[i];
		}
	}

	xSemaphoreGive(s_mutex);
	return NULL;
}

const zb_device_record_t *zb_device_mgr_get_by_short_addr(uint16_t short_addr)
{
	xSemaphoreTake(s_mutex, portMAX_DELAY);

	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr != 0ULL &&
		    s_device_table[i].network_addr == short_addr) {
			xSemaphoreGive(s_mutex);
			return &s_device_table[i];
		}
	}

	xSemaphoreGive(s_mutex);
	return NULL;
}

const zb_device_record_t *zb_device_mgr_get_all(uint8_t *count)
{
	if (count == NULL) {
		return NULL;
	}

	xSemaphoreTake(s_mutex, portMAX_DELAY);

	uint8_t active = 0;
	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr != 0ULL) {
			active++;
		}
	}
	*count = active;

	xSemaphoreGive(s_mutex);
	return s_device_table;
}

void zb_device_mgr_on_device_join(uint16_t short_addr, uint64_t ieee_addr,
                                  uint8_t device_type, uint8_t power_source)
{
	zb_device_mgr_add(ieee_addr, short_addr, device_type, power_source);
	zb_device_mgr_start_interview(ieee_addr);

	com_event_t evt = {
		.type = COM_EVT_DEVICE_JOINED,
	};
	evt.payload.device_joined.ieee_addr = ieee_addr;
	evt.payload.device_joined.network_addr = short_addr;
	evt.payload.device_joined.device_type = device_type;
	evt.payload.device_joined.power_source = power_source;
	com_pipeline_emit(&evt);
}

void zb_device_mgr_on_device_leave(uint64_t ieee_addr)
{
	zb_device_mgr_remove(ieee_addr);

	com_event_t evt = {
		.type = COM_EVT_DEVICE_LEFT,
	};
	evt.payload.device_left.ieee_addr = ieee_addr;
	evt.payload.device_left.reason = "left";
	com_pipeline_emit(&evt);
}

esp_err_t zb_device_mgr_start_interview(uint64_t ieee)
{
	const zb_device_record_t *dev = zb_device_mgr_get(ieee);
	if (dev == NULL) {
		return ESP_ERR_NOT_FOUND;
	}

	xSemaphoreTake(s_interview_mutex, portMAX_DELAY);
	s_interview_ctx.ieee_addr = ieee;
	s_interview_ctx.short_addr = dev->network_addr;
	s_interview_ctx.pending_endpoint = 0;
	xSemaphoreGive(s_interview_mutex);

	ESP_LOGI(TAG, "Starting interview for device 0x%016llX", ieee);

	esp_zb_zdo_active_ep_req_param_t req = { .addr_of_interest = dev->network_addr };
	esp_zb_zdo_active_ep_req(&req, zb_device_mgr_active_ep_cb, NULL);
	return ESP_OK;
}

static void zb_device_mgr_active_ep_cb(esp_zb_zdp_status_t zdo_status, uint8_t ep_count, uint8_t *ep_id_list, void *user_ctx)
{
	(void)user_ctx;

	if (zdo_status != ESP_ZB_ZDP_STATUS_SUCCESS) {
		ESP_LOGE(TAG, "Active EP request failed, status=%d", zdo_status);
		return;
	}

	xSemaphoreTake(s_interview_mutex, portMAX_DELAY);
	uint16_t short_addr = s_interview_ctx.short_addr;
	xSemaphoreGive(s_interview_mutex);

	for (uint8_t i = 0; i < ep_count; i++) {
		esp_zb_zdo_simple_desc_req_param_t req = {
			.addr_of_interest = short_addr,
			.endpoint = ep_id_list[i]
		};
		esp_zb_zdo_simple_desc_req(&req, zb_device_mgr_simple_desc_cb, NULL);
	}
}

static void zb_device_mgr_simple_desc_cb(esp_zb_zdp_status_t zdo_status, esp_zb_af_simple_desc_1_1_t *simple_desc, void *user_ctx)
{
	(void)user_ctx;

	if (zdo_status != ESP_ZB_ZDP_STATUS_SUCCESS || simple_desc == NULL) {
		ESP_LOGE(TAG, "Simple desc request failed, status=%d", zdo_status);
		return;
	}

	xSemaphoreTake(s_interview_mutex, portMAX_DELAY);
	uint64_t ieee = s_interview_ctx.ieee_addr;
	xSemaphoreGive(s_interview_mutex);

	xSemaphoreTake(s_mutex, portMAX_DELAY);
	int dev_idx = -1;
	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr == ieee) {
			dev_idx = i;
			break;
		}
	}

	if (dev_idx < 0) {
		xSemaphoreGive(s_mutex);
		ESP_LOGW(TAG, "Interview: device 0x%016llX not found", ieee);
		return;
	}

	zb_device_record_t *dev = &s_device_table[dev_idx];

	/* Check for duplicate endpoint */
	bool duplicate = false;
	for (int j = 0; j < dev->endpoint_count; j++) {
		if (dev->endpoints[j].ep_id == simple_desc->endpoint) {
			duplicate = true;
			break;
		}
	}
	if (duplicate) {
		xSemaphoreGive(s_mutex);
		ESP_LOGI(TAG, "EP %d already known for device 0x%016llX, skipping",
			 simple_desc->endpoint, ieee);
		return;
	}

	zb_endpoint_info_t *ep = NULL;
	if (dev->endpoint_count < ZB_MAX_EP_PER_DEVICE) {
		ep = &dev->endpoints[dev->endpoint_count];
		memset(ep, 0, sizeof(zb_endpoint_info_t));
		ep->ep_id = simple_desc->endpoint;

		uint8_t total_clusters = simple_desc->app_input_cluster_count +
					 simple_desc->app_output_cluster_count;
		uint8_t copy_count = (total_clusters > ZB_MAX_CLUSTERS_PER_EP)
					     ? ZB_MAX_CLUSTERS_PER_EP : total_clusters;
		for (uint8_t i = 0; i < copy_count; i++) {
			ep->clusters[i] = simple_desc->app_cluster_list[i];
		}
		ep->cluster_count = copy_count;
		dev->endpoint_count++;

		ESP_LOGI(TAG, "Added EP %d to device 0x%016llX (%d clusters)",
			 ep->ep_id, ieee, copy_count);
	} else {
		ESP_LOGW(TAG, "Device 0x%016llX EP limit reached", ieee);
	}

	uint16_t network_addr = dev->network_addr;
	uint8_t  new_ep_id    = 0;
	uint8_t  cluster_count = 0;
	uint16_t clusters[ZB_MAX_CLUSTERS_PER_EP] = {0};
	if (ep != NULL) {
		new_ep_id    = ep->ep_id;
		cluster_count = ep->cluster_count;
		memcpy(clusters, ep->clusters, sizeof(clusters));
	}

	xSemaphoreGive(s_mutex);

	/* Persist outside mutex to reduce lock time */
	s_save_table();

	/* Best-effort reporting setup for standard HA clusters on this endpoint. */
	if (ep != NULL) {
		for (uint8_t c = 0; c < cluster_count; c++) {
			s_configure_cluster_reports(network_addr, ieee, new_ep_id, clusters[c]);
		}
	}
}

void zb_device_mgr_handle_read_attr_resp(uint16_t short_addr, uint64_t ieee,
                                         uint8_t endpoint, uint16_t cluster_id,
                                         uint16_t attr_id, const void *value,
                                         uint8_t type)
{
	(void)short_addr;

	if (value == NULL) {
		return;
	}

	/* Ping uses Basic cluster; do not broadcast it as a state change. */
	if (cluster_id == ZB_PING_CLUSTER_ID) {
		return;
	}

	/* Emit state change for any read attr response */
	com_event_t evt = { .type = COM_EVT_STATE_CHANGE };
	evt.payload.state_change.ieee_addr = ieee;
	evt.payload.state_change.num_changes = 1;
	com_state_change_t *chg = &evt.payload.state_change.changes[0];
	snprintf(chg->cluster, sizeof(chg->cluster), "0x%04X", cluster_id);
	snprintf(chg->attribute, sizeof(chg->attribute), "0x%04X", attr_id);
	chg->endpoint = endpoint;

	switch (type) {
	case 0: chg->type = 2; chg->value.u_val = *(const uint8_t *)value; break;
	case 1: chg->type = 2; chg->value.u_val = *(const uint16_t *)value; break;
	case 2: chg->type = 2; chg->value.u_val = *(const uint32_t *)value; break;
	case 3: chg->type = 2; chg->value.u_val = (uint32_t)(*(const uint64_t *)value); break;
	case 4: chg->type = 0; chg->value.b_val = *(const bool *)value; break;
	case 5: chg->type = 1; chg->value.i_val = *(const int16_t *)value; break;
	default: chg->type = 2; chg->value.u_val = 0; break;
	}
	com_pipeline_emit(&evt);
}

const zb_endpoint_info_t *zb_device_mgr_find_ep_with_cluster(uint64_t ieee,
                                                             uint16_t cluster_id)
{
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr == ieee) {
			const zb_device_record_t *dev = &s_device_table[i];
			for (int j = 0; j < dev->endpoint_count; j++) {
				for (int k = 0; k < dev->endpoints[j].cluster_count; k++) {
					if (dev->endpoints[j].clusters[k] == cluster_id) {
						xSemaphoreGive(s_mutex);
						return &dev->endpoints[j];
					}
				}
			}
			break;
		}
	}
	xSemaphoreGive(s_mutex);
	return NULL;
}

const zb_endpoint_info_t *zb_device_mgr_get_endpoint(uint64_t ieee, uint8_t ep_id)
{
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr == ieee) {
			const zb_device_record_t *dev = &s_device_table[i];
			for (int j = 0; j < dev->endpoint_count; j++) {
				if (dev->endpoints[j].ep_id == ep_id) {
					xSemaphoreGive(s_mutex);
					return &dev->endpoints[j];
				}
			}
			break;
		}
	}
	xSemaphoreGive(s_mutex);
	return NULL;
}

uint8_t zb_device_mgr_get_endpoint_count(uint64_t ieee)
{
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	for (int i = 0; i < ZB_MAX_DEVICES; i++) {
		if (s_device_table[i].ieee_addr == ieee) {
			uint8_t count = s_device_table[i].endpoint_count;
			xSemaphoreGive(s_mutex);
			return count;
		}
	}
	xSemaphoreGive(s_mutex);
	return 0;
}

esp_err_t zb_device_mgr_save(void)
{
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	esp_err_t err = s_save_table();
	xSemaphoreGive(s_mutex);
	return err;
}

esp_err_t zb_device_mgr_load(void)
{
	if (s_mutex == NULL) {
		return ESP_ERR_INVALID_STATE;
	}

	xSemaphoreTake(s_mutex, portMAX_DELAY);

	size_t    len = sizeof(s_device_table);
	esp_err_t err = nvs_storage_get_blob("zb_devs", "device_table",
					      s_device_table, &len);
	if (err == ESP_ERR_NVS_NOT_FOUND) {
		memset(s_device_table, 0, sizeof(s_device_table));
		err = ESP_OK;
	} else if (err != ESP_OK) {
		ESP_LOGE(TAG, "Failed to load device table: %s", esp_err_to_name(err));
	} else if (len != sizeof(s_device_table)) {
		ESP_LOGW(TAG, "Device table size mismatch (%d vs %d), resetting",
			 (int)len, (int)sizeof(s_device_table));
		memset(s_device_table, 0, sizeof(s_device_table));
	}

	xSemaphoreGive(s_mutex);
	return err;
}

void zb_device_mgr_set_online(uint64_t ieee, bool online)
{
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	int idx = s_find_device_index(ieee);
	if (idx >= 0) {
		s_liveness_table[idx].online = online;
		s_save_liveness();
	}
	xSemaphoreGive(s_mutex);
}

void zb_device_mgr_touch_last_seen(uint64_t ieee)
{
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	int idx = s_find_device_index(ieee);
	if (idx >= 0) {
		s_liveness_table[idx].online = true;
		s_liveness_table[idx].last_seen_ms = esp_timer_get_time() / 1000;
		s_save_liveness();
	}
	xSemaphoreGive(s_mutex);
}

bool zb_device_mgr_is_online(uint64_t ieee)
{
	bool online = false;
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	int idx = s_find_device_index(ieee);
	if (idx >= 0) {
		online = s_liveness_table[idx].online;
	}
	xSemaphoreGive(s_mutex);
	return online;
}

int64_t zb_device_mgr_get_last_seen_ms(uint64_t ieee)
{
	int64_t last_seen = 0;
	xSemaphoreTake(s_mutex, portMAX_DELAY);
	int idx = s_find_device_index(ieee);
	if (idx >= 0) {
		last_seen = s_liveness_table[idx].last_seen_ms;
	}
	xSemaphoreGive(s_mutex);
	return last_seen;
}
