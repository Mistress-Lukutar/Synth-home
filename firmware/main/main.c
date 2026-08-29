#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "esp_event.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "nvs_storage.h"
#include "hub_config.h"
#include "com_pipeline.h"
#include "zb_stack.h"
#include "zb_device_mgr.h"
#include "zb_clusters.h"
#include "zb_cmd_tracker.h"
#include "serial_api.h"

static const char *TAG = "main";

/* Reporting policy may change between firmware builds; re-push it to every
 * saved device once the network is up so they do not need a re-pair. */
static void reporting_reconfig_task(void *arg)
{
	(void)arg;

	if (!zb_stack_wait_network_ready(30000)) {
		ESP_LOGW(TAG, "Network not ready in 30 s, skipping reporting reconfig");
		vTaskDelete(NULL);
		return;
	}
	/* Give the network a moment to settle before the ZCL burst. */
	vTaskDelay(pdMS_TO_TICKS(2000));
	zb_device_mgr_reconfigure_reporting();
	vTaskDelete(NULL);
}

static void on_attribute_report(uint16_t short_addr, uint64_t ieee_addr,
                                uint8_t endpoint, uint16_t cluster_id,
                                uint16_t attr_id, const void *value,
                                uint8_t type)
{
	(void)short_addr;

	/* Xiaomi private cluster reports are liveness noise, not UI state. */
	if (cluster_id == 0xFCC0) {
		zb_device_mgr_touch_last_seen(ieee_addr);
		return;
	}

	zb_cmd_tracker_on_report(ieee_addr, cluster_id, attr_id, value, type);
	zb_device_mgr_touch_last_seen(ieee_addr);

	com_event_t evt = {
		.type = COM_EVT_STATE_CHANGE,
	};
	evt.payload.state_change.ieee_addr = ieee_addr;
	evt.payload.state_change.num_changes = 1;

	com_state_change_t *chg = &evt.payload.state_change.changes[0];
	snprintf(chg->cluster, sizeof(chg->cluster), "0x%04X", cluster_id);
	snprintf(chg->attribute, sizeof(chg->attribute), "0x%04X", attr_id);
	chg->endpoint = endpoint;

	switch (type) {
	case 0: /* u8 */
		chg->type = 2; /* uint32 */
		chg->value.u_val = *(const uint8_t *)value;
		break;
	case 1: /* u16 */
		chg->type = 2; /* uint32 */
		chg->value.u_val = *(const uint16_t *)value;
		break;
	case 2: /* u32 */
		chg->type = 2; /* uint32 */
		chg->value.u_val = *(const uint32_t *)value;
		break;
	case 3: /* u64 */
		chg->type = 2; /* uint32 */
		chg->value.u_val = (uint32_t)(*(const uint64_t *)value);
		break;
	case 4: /* bool */
		chg->type = 0; /* bool */
		chg->value.b_val = *(const bool *)value;
		break;
	case 5: /* s16 */
		chg->type = 1; /* int32 */
		chg->value.i_val = *(const int16_t *)value;
		break;
	default:
		chg->type = 2;
		chg->value.u_val = 0;
		break;
	}

	com_pipeline_emit(&evt);
}

static void on_read_attr_resp(uint16_t short_addr, uint64_t ieee_addr,
                              uint8_t endpoint, uint16_t cluster_id,
                              uint16_t attr_id, const void *value,
                              uint8_t type)
{
	zb_cmd_tracker_on_report(ieee_addr, cluster_id, attr_id, value, type);
	zb_device_mgr_touch_last_seen(ieee_addr);
	zb_device_mgr_handle_read_attr_resp(short_addr, ieee_addr, endpoint,
					    cluster_id, attr_id, value, type);
}

void app_main(void)
{
	/* JSON lines are newline-framed, so console logs cannot corrupt the
	 * host protocol anymore; keep stack visibility for diagnostics. */
	esp_log_level_set("*", ESP_LOG_INFO);
	ESP_LOGI(TAG, "Starting Zigbee HUB application...");

	ESP_ERROR_CHECK(nvs_storage_init());
	ESP_ERROR_CHECK(esp_event_loop_create_default());
	ESP_ERROR_CHECK(hub_config_init());
	ESP_ERROR_CHECK(com_pipeline_init());


	ESP_ERROR_CHECK(zb_stack_init());
	ESP_ERROR_CHECK(zb_device_mgr_init());
	ESP_ERROR_CHECK(zb_cmd_tracker_init());
	zb_stack_register_callbacks(zb_device_mgr_on_device_join,
				    zb_device_mgr_on_device_leave,
				    on_attribute_report,
				    on_read_attr_resp);

	ESP_ERROR_CHECK(serial_api_init());

	BaseType_t ret = xTaskCreate(reporting_reconfig_task, "zb_reconfig",
				     8192, NULL, 4, NULL);
	if (ret != pdPASS) {
		ESP_LOGW(TAG, "Failed to start reporting reconfig task");
	}

	ESP_LOGI(TAG, "Zigbee HUB fully initialized");
}
