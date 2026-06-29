#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define COM_CORR_ID_LEN  40
#define COM_MAX_CHANGES  8

typedef enum {
	COM_EVT_CONNECTED,
	COM_EVT_STATE_CHANGE,
	COM_EVT_DEVICE_JOINED,
	COM_EVT_DEVICE_LEFT,
	COM_EVT_NETWORK_PERMIT_JOIN,
	COM_EVT_COMMAND_FAILED,
	COM_EVT_COMMAND_STATUS,
} com_event_type_t;

typedef struct {
	char cluster[32];
	char attribute[32];
	union {
		bool    b_val;
		int32_t i_val;
		uint32_t u_val;
		float   f_val;
	} value;
	uint8_t type; /* 0=bool, 1=int32, 2=uint32, 3=float */
	uint8_t endpoint;
} com_state_change_t;

typedef struct {
	uint64_t ieee_addr;
	uint16_t network_addr;
	uint8_t  device_type;
	uint8_t  power_source;
} com_device_joined_t;

typedef struct {
	uint64_t ieee_addr;
	const char *reason;
} com_device_left_t;

typedef struct {
	bool     active;
	uint16_t duration_remaining;
} com_permit_join_t;

typedef enum {
	CMD_STATUS_PENDING,
	CMD_STATUS_DELIVERED,
	CMD_STATUS_COMPLETED,
	CMD_STATUS_FAILED,
	CMD_STATUS_TIMEOUT,
} com_cmd_status_t;

typedef struct {
	char correlation_id[COM_CORR_ID_LEN];
	com_cmd_status_t status;
	char reason[32];
	uint64_t ieee_addr;
	uint16_t cluster_id;
} com_command_status_t;

typedef struct {
	char correlation_id[COM_CORR_ID_LEN];
	char error[32];
	char message[64];
} com_command_failed_t;

typedef struct {
	com_event_type_t type;
	union {
		struct {
			uint64_t           ieee_addr;
			com_state_change_t changes[COM_MAX_CHANGES];
			uint8_t            num_changes;
		} state_change;
		com_device_joined_t  device_joined;
		com_device_left_t    device_left;
		com_permit_join_t    permit_join;
		com_command_failed_t command_failed;
		com_command_status_t command_status;
	} payload;
} com_event_t;

typedef void (*com_pipeline_cb_t)(const com_event_t *event, void *user_data);

esp_err_t com_pipeline_init(void);
esp_err_t com_pipeline_emit(const com_event_t *event);
esp_err_t com_pipeline_subscribe(com_pipeline_cb_t cb, void *user_data);

/* Serialize event to newly allocated JSON string. Caller must cJSON_free() it. */
char *com_pipeline_event_to_json(const com_event_t *event);

#ifdef __cplusplus
}
#endif
