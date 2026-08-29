#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZB_CMD_TRACKER_TIMEOUT_MS 5000

esp_err_t zb_cmd_tracker_init(void);

/* Register a command for tracking. corr_id must be unique per in-flight command. */
esp_err_t zb_cmd_tracker_register(const char *corr_id, uint64_t ieee,
                                  uint8_t endpoint, uint16_t cluster_id,
                                  uint16_t attr_id, bool is_write,
                                  bool check_value, uint32_t expected_val,
                                  uint32_t timeout_ms);

/*
 * Split registration for callers that must reserve a slot *before* sending the
 * command and only commit it after a successful transmit. This prevents the
 * "command sent but no tracking slot" bug.
 *
 * Typical flow:
 *   int slot = zb_cmd_tracker_reserve();
 *   if (slot < 0) return ESP_ERR_NO_MEM;
 *   <acquire zigbee lock, send command>
 *   if (send_failed) { zb_cmd_tracker_release(slot); return error; }
 *   zb_cmd_tracker_commit(slot, corr_id, ..., is_write);
 */
int  zb_cmd_tracker_reserve(void);
void zb_cmd_tracker_commit(int slot, const char *corr_id, uint64_t ieee,
                           uint8_t endpoint, uint16_t cluster_id,
                           uint16_t attr_id, bool is_write, bool check_value,
                           uint32_t expected_val, uint32_t timeout_ms);
void zb_cmd_tracker_release(int slot);

/* Call from attribute report handler (e.g. on_attribute_report). */
void zb_cmd_tracker_on_report(uint64_t ieee, uint16_t cluster_id, uint16_t attr_id,
                              const void *value, uint8_t type);

/* Call from ZCL Default Response handler if available. */
void zb_cmd_tracker_on_default_resp(uint64_t ieee, uint16_t cluster_id,
                                    uint8_t cmd_id, uint8_t zcl_status);

#ifdef __cplusplus
}
#endif
