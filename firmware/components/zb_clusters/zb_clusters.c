#include <string.h>
#include "esp_log.h"
#include "zb_clusters.h"
#include "zb_device_mgr.h"
#include "zb_stack.h"
#include "com_pipeline.h"
#include "zb_cmd_tracker.h"
#include "esp_zigbee_core.h"
#include "zcl/esp_zigbee_zcl_command.h"
#include "zdo/esp_zigbee_zdo_command.h"

static const char *TAG = "zb_clusters";

/* -------------------------------------------------------------------------- */
/* Internal helpers                                                           */
/* -------------------------------------------------------------------------- */

static void emit_command_failed(const char *corr_id, const char *error,
                                const char *message)
{
	com_event_t evt = {
		.type = COM_EVT_COMMAND_FAILED,
	};

	if (corr_id) {
		strncpy(evt.payload.command_failed.correlation_id, corr_id,
			COM_CORR_ID_LEN - 1);
		evt.payload.command_failed.correlation_id[COM_CORR_ID_LEN - 1] = '\0';
	} else {
		evt.payload.command_failed.correlation_id[0] = '\0';
	}

	if (error) {
		strncpy(evt.payload.command_failed.error, error,
			sizeof(evt.payload.command_failed.error) - 1);
		evt.payload.command_failed.error[sizeof(evt.payload.command_failed.error) - 1] = '\0';
	} else {
		evt.payload.command_failed.error[0] = '\0';
	}

	if (message) {
		strncpy(evt.payload.command_failed.message, message,
			sizeof(evt.payload.command_failed.message) - 1);
		evt.payload.command_failed.message[sizeof(evt.payload.command_failed.message) - 1] = '\0';
	} else {
		evt.payload.command_failed.message[0] = '\0';
	}

	esp_err_t err = com_pipeline_emit(&evt);
	if (err != ESP_OK) {
		ESP_LOGE(TAG, "Failed to emit command_failed event: %s",
			 esp_err_to_name(err));
	}
}

static esp_err_t get_device_and_ep(uint64_t ieee, uint16_t cluster_id,
                                   uint8_t ep_id, const char *corr_id,
                                   const zb_device_record_t **out_dev,
                                   const zb_endpoint_info_t **out_ep)
{
	const zb_device_record_t *dev = zb_device_mgr_get(ieee);
	if (dev == NULL) {
		ESP_LOGW(TAG, "Device not found for IEEE 0x%016llX", ieee);
		emit_command_failed(corr_id, "DEVICE_NOT_FOUND", "Device not found");
		return ESP_ERR_NOT_FOUND;
	}

	const zb_endpoint_info_t *ep = NULL;
	if (ep_id != 0) {
		ep = zb_device_mgr_get_endpoint(ieee, ep_id);
		if (ep == NULL) {
			ESP_LOGW(TAG, "Endpoint %d not found for IEEE 0x%016llX", ep_id, ieee);
			emit_command_failed(corr_id, "EP_NOT_FOUND", "Endpoint not found");
			return ESP_ERR_NOT_FOUND;
		}
		/* Verify the endpoint actually has the requested cluster */
		bool has_cluster = false;
		for (uint8_t i = 0; i < ep->cluster_count; i++) {
			if (ep->clusters[i] == cluster_id) {
				has_cluster = true;
				break;
			}
		}
		if (!has_cluster) {
			ESP_LOGW(TAG, "Endpoint %d missing cluster 0x%04X", ep_id, cluster_id);
			emit_command_failed(corr_id, "CLUSTER_NOT_FOUND",
					    "Cluster not present on endpoint");
			return ESP_ERR_NOT_FOUND;
		}
	} else {
		ep = zb_device_mgr_find_ep_with_cluster(ieee, cluster_id);
		if (ep == NULL) {
			ESP_LOGW(TAG, "No endpoint with cluster 0x%04X for IEEE 0x%016llX",
				 cluster_id, ieee);
			emit_command_failed(corr_id, "CLUSTER_NOT_FOUND",
					    "No endpoint supports this cluster");
			return ESP_ERR_NOT_FOUND;
		}
	}

	ESP_LOGI(TAG, "Using EP %d for cluster 0x%04X on 0x%016llX",
		 ep->ep_id, cluster_id, ieee);

	*out_dev = dev;
	*out_ep = ep;
	return ESP_OK;
}

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

esp_err_t zb_cluster_send_on_off(uint64_t ieee, uint8_t cmd_id,
                                 const char *corr_id, uint8_t ep_id)
{
	if (cmd_id > ZB_CMD_ON_OFF_TOGGLE) {
		emit_command_failed(corr_id, "INVALID_ARG", "Invalid On/Off command ID");
		return ESP_ERR_INVALID_ARG;
	}

	const zb_device_record_t *dev;
	const zb_endpoint_info_t *ep;
	esp_err_t ret = get_device_and_ep(ieee, 0x0006, ep_id, corr_id, &dev, &ep);
	if (ret != ESP_OK) {
		return ret;
	}

	esp_zb_zcl_on_off_cmd_t cmd_req = {
		.zcl_basic_cmd = {
			.dst_addr_u.addr_short = dev->network_addr,
			.dst_endpoint = ep->ep_id,
			.src_endpoint = 1,
		},
		.address_mode = ESP_ZB_APS_ADDR_MODE_16_ENDP_PRESENT,
		.on_off_cmd_id = cmd_id,
	};

	int slot = zb_cmd_tracker_reserve();
	if (slot < 0) {
		ESP_LOGE(TAG, "No free tracker slot for On/Off");
		emit_command_failed(corr_id, "TRACKER_FULL",
				    "No free command tracking slots");
		return ESP_ERR_NO_MEM;
	}

	if (!esp_zb_lock_acquire(pdMS_TO_TICKS(1000))) {
		ESP_LOGE(TAG, "Failed to acquire Zigbee lock for ON/OFF");
		emit_command_failed(corr_id, "ZIGBEE_LOCK_TIMEOUT", "Zigbee stack busy");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}
	uint8_t status = esp_zb_zcl_on_off_cmd_req(&cmd_req);
	esp_zb_lock_release();
	if (status == 0xFF) {
		ESP_LOGE(TAG, "Failed to send On/Off command");
		emit_command_failed(corr_id, "ZCL_SEND_FAILED",
				    "Failed to send ZCL command");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}

	bool on = (cmd_id == ZB_CMD_ON_OFF_ON);
	bool off = (cmd_id == ZB_CMD_ON_OFF_OFF);
	if (on || off) {
		zb_cmd_tracker_commit(slot, corr_id, ieee, ep->ep_id, 0x0006, 0x0000,
				      true, true, on ? 1U : 0U,
				      ZB_CMD_TRACKER_TIMEOUT_MS);
	} else {
		zb_cmd_tracker_commit(slot, corr_id, ieee, ep->ep_id, 0x0006, 0xFFFF,
				      true, false, 0,
				      ZB_CMD_TRACKER_TIMEOUT_MS);
	}
	return ESP_OK;
}

esp_err_t zb_cluster_send_level(uint64_t ieee, uint8_t level,
                                uint16_t transition, const char *corr_id,
                                uint8_t ep_id)
{
	const zb_device_record_t *dev;
	const zb_endpoint_info_t *ep;
	esp_err_t ret = get_device_and_ep(ieee, 0x0008, ep_id, corr_id, &dev, &ep);
	if (ret != ESP_OK) {
		return ret;
	}

	esp_zb_zcl_move_to_level_cmd_t cmd_req = {
		.zcl_basic_cmd = {
			.dst_addr_u.addr_short = dev->network_addr,
			.dst_endpoint = ep->ep_id,
			.src_endpoint = 1,
		},
		.address_mode = ESP_ZB_APS_ADDR_MODE_16_ENDP_PRESENT,
		.level = level,
		.transition_time = transition,
	};

	int slot = zb_cmd_tracker_reserve();
	if (slot < 0) {
		ESP_LOGE(TAG, "No free tracker slot for Level");
		emit_command_failed(corr_id, "TRACKER_FULL",
				    "No free command tracking slots");
		return ESP_ERR_NO_MEM;
	}

	if (!esp_zb_lock_acquire(pdMS_TO_TICKS(1000))) {
		ESP_LOGE(TAG, "Failed to acquire Zigbee lock for Level");
		emit_command_failed(corr_id, "ZIGBEE_LOCK_TIMEOUT", "Zigbee stack busy");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}
	uint8_t status = esp_zb_zcl_level_move_to_level_cmd_req(&cmd_req);
	esp_zb_lock_release();
	if (status == 0xFF) {
		ESP_LOGE(TAG, "Failed to send Level command");
		emit_command_failed(corr_id, "ZCL_SEND_FAILED",
				    "Failed to send ZCL command");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}

	zb_cmd_tracker_commit(slot, corr_id, ieee, ep->ep_id, 0x0008, 0x0000,
			      true, true, level,
			      ZB_CMD_TRACKER_TIMEOUT_TRANSITION_MS);
	return ESP_OK;
}

esp_err_t zb_cluster_send_color_hs(uint64_t ieee, uint8_t hue, uint8_t sat,
                                   uint16_t transition, const char *corr_id,
                                   uint8_t ep_id)
{
	const zb_device_record_t *dev;
	const zb_endpoint_info_t *ep;
	esp_err_t ret = get_device_and_ep(ieee, 0x0300, ep_id, corr_id, &dev, &ep);
	if (ret != ESP_OK) {
		return ret;
	}

	esp_zb_color_move_to_hue_saturation_cmd_t cmd_req = {
		.zcl_basic_cmd = {
			.dst_addr_u.addr_short = dev->network_addr,
			.dst_endpoint = ep->ep_id,
			.src_endpoint = 1,
		},
		.address_mode = ESP_ZB_APS_ADDR_MODE_16_ENDP_PRESENT,
		.hue = hue,
		.saturation = sat,
		.transition_time = transition,
	};

	int slot = zb_cmd_tracker_reserve();
	if (slot < 0) {
		ESP_LOGE(TAG, "No free tracker slot for Color HS");
		emit_command_failed(corr_id, "TRACKER_FULL",
				    "No free command tracking slots");
		return ESP_ERR_NO_MEM;
	}

	if (!esp_zb_lock_acquire(pdMS_TO_TICKS(1000))) {
		ESP_LOGE(TAG, "Failed to acquire Zigbee lock for Color HS");
		emit_command_failed(corr_id, "ZIGBEE_LOCK_TIMEOUT", "Zigbee stack busy");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}
	uint8_t status = esp_zb_zcl_color_move_to_hue_and_saturation_cmd_req(&cmd_req);
	esp_zb_lock_release();
	if (status == 0xFF) {
		ESP_LOGE(TAG, "Failed to send Color HS command");
		emit_command_failed(corr_id, "ZCL_SEND_FAILED",
				    "Failed to send ZCL command");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}

	zb_cmd_tracker_commit(slot, corr_id, ieee, ep->ep_id, 0x0300, 0x0000,
			      true, true, hue,
			      ZB_CMD_TRACKER_TIMEOUT_TRANSITION_MS);
	return ESP_OK;
}

esp_err_t zb_cluster_send_color_xy(uint64_t ieee, uint16_t x, uint16_t y,
                                   uint16_t transition, const char *corr_id,
                                   uint8_t ep_id)
{
	const zb_device_record_t *dev;
	const zb_endpoint_info_t *ep;
	esp_err_t ret = get_device_and_ep(ieee, 0x0300, ep_id, corr_id, &dev, &ep);
	if (ret != ESP_OK) {
		return ret;
	}

	esp_zb_zcl_color_move_to_color_cmd_t cmd_req = {
		.zcl_basic_cmd = {
			.dst_addr_u.addr_short = dev->network_addr,
			.dst_endpoint = ep->ep_id,
			.src_endpoint = 1,
		},
		.address_mode = ESP_ZB_APS_ADDR_MODE_16_ENDP_PRESENT,
		.color_x = x,
		.color_y = y,
		.transition_time = transition,
	};

	int slot = zb_cmd_tracker_reserve();
	if (slot < 0) {
		ESP_LOGE(TAG, "No free tracker slot for Color XY");
		emit_command_failed(corr_id, "TRACKER_FULL",
				    "No free command tracking slots");
		return ESP_ERR_NO_MEM;
	}

	if (!esp_zb_lock_acquire(pdMS_TO_TICKS(1000))) {
		ESP_LOGE(TAG, "Failed to acquire Zigbee lock for Color XY");
		emit_command_failed(corr_id, "ZIGBEE_LOCK_TIMEOUT", "Zigbee stack busy");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}
	uint8_t status = esp_zb_zcl_color_move_to_color_cmd_req(&cmd_req);
	esp_zb_lock_release();
	if (status == 0xFF) {
		ESP_LOGE(TAG, "Failed to send Color XY command");
		emit_command_failed(corr_id, "ZCL_SEND_FAILED",
				    "Failed to send ZCL command");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}

	zb_cmd_tracker_commit(slot, corr_id, ieee, ep->ep_id, 0x0300, 0x0003,
			      true, true, x, ZB_CMD_TRACKER_TIMEOUT_TRANSITION_MS);
	return ESP_OK;
}

esp_err_t zb_cluster_send_color_ct(uint64_t ieee, uint16_t mireds,
                                   uint16_t transition, const char *corr_id,
                                   uint8_t ep_id)
{
	const zb_device_record_t *dev;
	const zb_endpoint_info_t *ep;
	esp_err_t ret = get_device_and_ep(ieee, 0x0300, ep_id, corr_id, &dev, &ep);
	if (ret != ESP_OK) {
		return ret;
	}

	esp_zb_zcl_color_move_to_color_temperature_cmd_t cmd_req = {
		.zcl_basic_cmd = {
			.dst_addr_u.addr_short = dev->network_addr,
			.dst_endpoint = ep->ep_id,
			.src_endpoint = 1,
		},
		.address_mode = ESP_ZB_APS_ADDR_MODE_16_ENDP_PRESENT,
		.color_temperature = mireds,
		.transition_time = transition,
	};

	int slot = zb_cmd_tracker_reserve();
	if (slot < 0) {
		ESP_LOGE(TAG, "No free tracker slot for Color CT");
		emit_command_failed(corr_id, "TRACKER_FULL",
				    "No free command tracking slots");
		return ESP_ERR_NO_MEM;
	}

	if (!esp_zb_lock_acquire(pdMS_TO_TICKS(1000))) {
		ESP_LOGE(TAG, "Failed to acquire Zigbee lock for Color CT");
		emit_command_failed(corr_id, "ZIGBEE_LOCK_TIMEOUT", "Zigbee stack busy");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}
	uint8_t status = esp_zb_zcl_color_move_to_color_temperature_cmd_req(&cmd_req);
	esp_zb_lock_release();
	if (status == 0xFF) {
		ESP_LOGE(TAG, "Failed to send Color CT command");
		emit_command_failed(corr_id, "ZCL_SEND_FAILED",
				    "Failed to send ZCL command");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}

	zb_cmd_tracker_commit(slot, corr_id, ieee, ep->ep_id, 0x0300, 0x0007,
			      true, true, mireds,
			      ZB_CMD_TRACKER_TIMEOUT_TRANSITION_MS);
	return ESP_OK;
}

static esp_err_t s_cluster_read_attr(uint64_t ieee, uint8_t ep_id,
                                     uint16_t cluster_id, uint16_t attr_id,
                                     const char *corr_id, bool silent)
{
	const zb_device_record_t *dev;
	const zb_endpoint_info_t *ep;
	esp_err_t ret = get_device_and_ep(ieee, cluster_id, ep_id, corr_id, &dev, &ep);
	if (ret != ESP_OK) {
		return ret;
	}

	uint16_t attr = attr_id;
	esp_zb_zcl_read_attr_cmd_t read_req = {
		.zcl_basic_cmd = {
			.dst_addr_u.addr_short = dev->network_addr,
			.dst_endpoint = ep->ep_id,
			.src_endpoint = 1,
		},
		.address_mode = ESP_ZB_APS_ADDR_MODE_16_ENDP_PRESENT,
		.clusterID = cluster_id,
		.attr_number = 1,
		.attr_field = &attr,
	};

	int slot = -1;
	if (silent) {
		slot = zb_cmd_tracker_reserve();
		if (slot < 0) {
			ESP_LOGE(TAG, "No free tracker slot for ping/read attr");
			emit_command_failed(corr_id, "TRACKER_FULL",
					    "No free command tracking slots");
			return ESP_ERR_NO_MEM;
		}
	}

	if (!esp_zb_lock_acquire(pdMS_TO_TICKS(1000))) {
		ESP_LOGE(TAG, "Failed to acquire Zigbee lock for read attr");
		emit_command_failed(corr_id, "ZIGBEE_LOCK_TIMEOUT", "Zigbee stack busy");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}
	uint8_t status = esp_zb_zcl_read_attr_cmd_req(&read_req);
	esp_zb_lock_release();
	if (status == 0xFF) {
		ESP_LOGE(TAG, "Failed to send read attr command");
		emit_command_failed(corr_id, "ZCL_SEND_FAILED",
				    "Failed to send ZCL read attr command");
		zb_cmd_tracker_release(slot);
		return ESP_FAIL;
	}

	if (silent) {
		zb_cmd_tracker_commit(slot, corr_id, ieee, ep->ep_id, cluster_id, attr_id,
				      false, false, 0, ZB_PING_TIMEOUT_MS);
	}

	return ESP_OK;
}

esp_err_t zb_cluster_read_attr(uint64_t ieee, uint8_t ep_id,
                               uint16_t cluster_id, uint16_t attr_id,
                               const char *corr_id)
{
	return s_cluster_read_attr(ieee, ep_id, cluster_id, attr_id, corr_id, false);
}

esp_err_t zb_cluster_ping(uint64_t ieee, const char *corr_id)
{
	return s_cluster_read_attr(ieee, 0, ZB_PING_CLUSTER_ID, ZB_PING_ATTR_ID,
				   corr_id, true);
}

/* -------------------------------------------------------------------------- */
/* Interview helpers: bind + configure reporting                              */
/* -------------------------------------------------------------------------- */

static void s_bind_req_cb(esp_zb_zdp_status_t zdo_status, void *user_ctx)
{
	uint16_t cluster_id = (uint16_t)(uintptr_t)user_ctx;

	if (zdo_status != ESP_ZB_ZDP_STATUS_SUCCESS) {
		ESP_LOGW(TAG, "Bind request failed for cluster 0x%04X, status=%d",
			 cluster_id, zdo_status);
	} else {
		ESP_LOGI(TAG, "Bind request succeeded for cluster 0x%04X", cluster_id);
	}
}

esp_err_t zb_cluster_send_bind_req(uint16_t network_addr, uint64_t ieee_addr,
                                   uint8_t ep_id, uint16_t cluster_id)
{
	esp_zb_ieee_addr_t coord_ieee;
	esp_zb_ieee_addr_t src_ieee;

	memset(coord_ieee, 0, sizeof(coord_ieee));
	memset(src_ieee, 0, sizeof(src_ieee));

	if (!esp_zb_lock_acquire(pdMS_TO_TICKS(1000))) {
		ESP_LOGE(TAG, "Failed to acquire Zigbee lock for bind request");
		return ESP_FAIL;
	}
	esp_zb_get_long_address(coord_ieee);
	esp_zb_lock_release();

	memcpy(src_ieee, &ieee_addr, sizeof(src_ieee));

	esp_zb_zdo_bind_req_param_t bind_req = {
		.src_endp = ep_id,
		.cluster_id = cluster_id,
		.dst_addr_mode = ESP_ZB_ZDO_BIND_DST_ADDR_MODE_64_BIT_EXTENDED,
		.dst_endp = 1,
		.req_dst_addr = network_addr,
	};
	memcpy(bind_req.src_address, src_ieee, sizeof(bind_req.src_address));
	memcpy(bind_req.dst_address_u.addr_long, coord_ieee,
	       sizeof(bind_req.dst_address_u.addr_long));

	if (!esp_zb_lock_acquire(pdMS_TO_TICKS(1000))) {
		ESP_LOGE(TAG, "Failed to acquire Zigbee lock for bind request");
		return ESP_FAIL;
	}
	esp_zb_zdo_device_bind_req(&bind_req, s_bind_req_cb,
				   (void *)(uintptr_t)cluster_id);
	esp_zb_lock_release();

	return ESP_OK;
}

esp_err_t zb_cluster_send_configure_reporting(uint16_t network_addr, uint8_t ep_id,
                                              uint16_t cluster_id, uint16_t attr_id,
                                              uint8_t attr_type)
{
	/*
	 * Reporting policy: push changes at most once per second and refresh at
	 * most hourly. The idle 4 events/s flood was caused by max_interval=1
	 * (forced periodic re-send), not by the reportable change, so the delta
	 * stays at 1: a coarser threshold silently swallows small adjustments
	 * and, worse, the settled value at the end of a dimming ramp when the
	 * last ramp report landed within the threshold of the target level —
	 * the UI then sticks on an intermediate value until max_interval.
	 * Ramp report rate stays bounded by min_interval.
	 */
	uint16_t min_interval = 1;
	uint16_t max_interval = 3600;

	uint8_t reportable_u8 = 1;
	uint16_t reportable_u16 = 1;
	void *reportable_change =
		(attr_type == ESP_ZB_ZCL_ATTR_TYPE_U16) ?
		(void *)&reportable_u16 : (void *)&reportable_u8;

	esp_zb_zcl_config_report_record_t record = {
		.direction = ESP_ZB_ZCL_REPORT_DIRECTION_SEND,
		.attributeID = attr_id,
		.attrType = attr_type,
		.min_interval = min_interval,
		.max_interval = max_interval,
		.reportable_change = reportable_change,
	};

	esp_zb_zcl_config_report_cmd_t cmd_req = {
		.zcl_basic_cmd = {
			.dst_addr_u.addr_short = network_addr,
			.dst_endpoint = ep_id,
			.src_endpoint = 1,
		},
		.address_mode = ESP_ZB_APS_ADDR_MODE_16_ENDP_PRESENT,
		.clusterID = cluster_id,
		.record_number = 1,
		.record_field = &record,
	};

	if (!esp_zb_lock_acquire(pdMS_TO_TICKS(1000))) {
		ESP_LOGE(TAG, "Failed to acquire Zigbee lock for configure reporting");
		return ESP_FAIL;
	}
	uint8_t status = esp_zb_zcl_config_report_cmd_req(&cmd_req);
	esp_zb_lock_release();
	if (status == 0xFF) {
		ESP_LOGE(TAG,
			 "Configure reporting failed for cluster 0x%04X attr 0x%04X",
			 cluster_id, attr_id);
		return ESP_FAIL;
	}
	return ESP_OK;
}
