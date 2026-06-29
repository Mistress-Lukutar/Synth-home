#pragma once

#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* On/Off cluster commands */
#define ZB_CMD_ON_OFF_OFF    0x00
#define ZB_CMD_ON_OFF_ON     0x01
#define ZB_CMD_ON_OFF_TOGGLE 0x02

/* Ping uses Basic cluster so it never touches OnOff state */
#define ZB_PING_CLUSTER_ID   0x0000
#define ZB_PING_ATTR_ID      0x0000
#define ZB_PING_TIMEOUT_MS   2000

esp_err_t zb_cluster_send_on_off(uint64_t ieee, uint8_t cmd_id,
                                 const char *corr_id, uint8_t ep_id);

esp_err_t zb_cluster_send_level(uint64_t ieee, uint8_t level,
                                uint16_t transition, const char *corr_id,
                                uint8_t ep_id);

esp_err_t zb_cluster_send_color_hs(uint64_t ieee, uint8_t hue, uint8_t sat,
                                   uint16_t transition, const char *corr_id,
                                   uint8_t ep_id);

esp_err_t zb_cluster_send_color_xy(uint64_t ieee, uint16_t x, uint16_t y,
                                   uint16_t transition, const char *corr_id,
                                   uint8_t ep_id);

esp_err_t zb_cluster_send_color_ct(uint64_t ieee, uint16_t mireds,
                                   uint16_t transition, const char *corr_id,
                                   uint8_t ep_id);

esp_err_t zb_cluster_read_attr(uint64_t ieee, uint8_t ep_id,
                               uint16_t cluster_id, uint16_t attr_id,
                               const char *corr_id);

esp_err_t zb_cluster_ping(uint64_t ieee, const char *corr_id);

#ifdef __cplusplus
}
#endif
