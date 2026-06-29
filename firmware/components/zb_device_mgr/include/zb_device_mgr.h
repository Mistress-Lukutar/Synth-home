#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ZB_DEVICE_NAME_LEN       32
#define ZB_MAX_DEVICES           32
#define ZB_MAX_EP_PER_DEVICE     4
#define ZB_MAX_CLUSTERS_PER_EP   8

typedef struct {
	uint8_t  ep_id;
	uint16_t clusters[ZB_MAX_CLUSTERS_PER_EP];
	uint8_t  cluster_count;
	bool     supports_hs;
	bool     supports_xy;
	bool     supports_ct;
	bool     supports_color_loop;
} zb_endpoint_info_t;

typedef struct {
	uint64_t ieee_addr;
	uint16_t network_addr;
	uint8_t  device_type;
	uint8_t  power_source;
	zb_endpoint_info_t endpoints[ZB_MAX_EP_PER_DEVICE];
	uint8_t  endpoint_count;
	char     friendly_name[ZB_DEVICE_NAME_LEN];
} zb_device_record_t;

esp_err_t zb_device_mgr_init(void);

esp_err_t zb_device_mgr_add(uint64_t ieee, uint16_t nwk_addr,
                            uint8_t dev_type, uint8_t power_source);

esp_err_t zb_device_mgr_remove(uint64_t ieee);

const zb_device_record_t *zb_device_mgr_get(uint64_t ieee);

const zb_device_record_t *zb_device_mgr_get_by_short_addr(uint16_t short_addr);

const zb_device_record_t *zb_device_mgr_get_all(uint8_t *count);

esp_err_t zb_device_mgr_start_interview(uint64_t ieee);

void zb_device_mgr_on_device_join(uint16_t short_addr, uint64_t ieee_addr,
                                  uint8_t device_type, uint8_t power_source);

void zb_device_mgr_on_device_leave(uint64_t ieee_addr);

void zb_device_mgr_handle_read_attr_resp(uint16_t short_addr, uint64_t ieee,
                                         uint8_t endpoint, uint16_t cluster_id,
                                         uint16_t attr_id, const void *value,
                                         uint8_t type);

const zb_endpoint_info_t *zb_device_mgr_find_ep_with_cluster(uint64_t ieee,
                                                             uint16_t cluster_id);

const zb_endpoint_info_t *zb_device_mgr_get_endpoint(uint64_t ieee, uint8_t ep_id);

uint8_t zb_device_mgr_get_endpoint_count(uint64_t ieee);

esp_err_t zb_device_mgr_save(void);
esp_err_t zb_device_mgr_load(void);

void zb_device_mgr_set_online(uint64_t ieee, bool online);
void zb_device_mgr_touch_last_seen(uint64_t ieee);
bool zb_device_mgr_is_online(uint64_t ieee);
int64_t zb_device_mgr_get_last_seen_ms(uint64_t ieee);

#ifdef __cplusplus
}
#endif
