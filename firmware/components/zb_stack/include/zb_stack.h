#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZB_PAN_ID_DEFAULT  0x1A62
#define ZB_CHANNEL_DEFAULT 11

typedef void (*zb_stack_device_join_cb_t)(uint16_t short_addr,
                                          uint64_t ieee_addr,
                                          uint8_t  device_type,
                                          uint8_t  power_source);

typedef void (*zb_stack_device_leave_cb_t)(uint64_t ieee_addr);

typedef void (*zb_stack_attribute_report_cb_t)(uint16_t short_addr,
                                               uint64_t ieee_addr,
                                               uint8_t  endpoint,
                                               uint16_t cluster_id,
                                               uint16_t attr_id,
                                               const void *value,
                                               uint8_t  type);

typedef void (*zb_stack_read_attr_resp_cb_t)(uint16_t short_addr,
                                             uint64_t ieee_addr,
                                             uint8_t  endpoint,
                                             uint16_t cluster_id,
                                             uint16_t attr_id,
                                             const void *value,
                                             uint8_t  type);

esp_err_t zb_stack_init(void);
esp_err_t zb_stack_start_network(void);
esp_err_t zb_stack_permit_join(uint8_t duration_sec);

/* Block until the Zigbee network is operational (steering done). */
bool zb_stack_wait_network_ready(uint32_t timeout_ms);

void zb_stack_register_callbacks(zb_stack_device_join_cb_t  join_cb,
                                 zb_stack_device_leave_cb_t leave_cb,
                                 zb_stack_attribute_report_cb_t report_cb,
                                 zb_stack_read_attr_resp_cb_t read_attr_cb);

esp_err_t zb_stack_send_zcl_cmd(uint16_t short_addr,
                                uint8_t  endpoint,
                                uint16_t cluster_id,
                                uint8_t  cmd_id,
                                const uint8_t *payload,
                                uint8_t  payload_len);

uint8_t zb_stack_get_next_seq_num(void);

#ifdef __cplusplus
}
#endif
