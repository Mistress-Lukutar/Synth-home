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
                                  uint16_t cluster_id, uint16_t attr_id,
                                  bool check_value, uint32_t expected_val,
                                  uint32_t timeout_ms);

/* Call from attribute report handler (e.g. on_attribute_report). */
void zb_cmd_tracker_on_report(uint64_t ieee, uint16_t cluster_id, uint16_t attr_id,
                              const void *value, uint8_t type);

/* Call from ZCL Default Response handler if available. */
void zb_cmd_tracker_on_default_resp(uint64_t ieee, uint16_t cluster_id,
                                    uint8_t cmd_id, uint8_t zcl_status);

#ifdef __cplusplus
}
#endif
