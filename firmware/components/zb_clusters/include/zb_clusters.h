#pragma once

#include <stdint.h>
#include <stdbool.h>
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

/* Upper bound of attribute ids per multi-attribute read command. */
#define ZB_READ_ATTRS_MAX   16

esp_err_t zb_clusters_init(void);

esp_err_t zb_cluster_send_on_off(uint64_t ieee, uint8_t cmd_id,
                                 const char *corr_id, uint8_t ep_id);

/* with_on_off: use MoveToLevelWithOnOff so a lamp turning on applies the
 * level atomically instead of ignoring MoveToLevel while transitioning
 * from off. */
esp_err_t zb_cluster_send_level(uint64_t ieee, uint8_t level,
                                uint16_t transition, const char *corr_id,
                                uint8_t ep_id, bool with_on_off);

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

/* Read several attributes of one cluster with a single ZCL Read Attributes
 * command (one frame on air instead of N). */
esp_err_t zb_cluster_read_attrs(uint64_t ieee, uint8_t ep_id,
                                uint16_t cluster_id, const uint16_t *attr_ids,
                                uint8_t attr_count, const char *corr_id);

esp_err_t zb_cluster_ping(uint64_t ieee, const char *corr_id);

/* Interview helpers: bind the device to the coordinator and configure reporting. */
esp_err_t zb_cluster_send_bind_req(uint16_t network_addr, uint64_t ieee_addr,
                                   uint8_t ep_id, uint16_t cluster_id);

esp_err_t zb_cluster_send_configure_reporting(uint16_t network_addr, uint8_t ep_id,
                                              uint16_t cluster_id, uint16_t attr_id,
                                              uint8_t attr_type);

#ifdef __cplusplus
}
#endif
