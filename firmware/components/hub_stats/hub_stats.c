/**
 * @file   hub_stats.c
 * @brief  Global loss/traffic counters for stability diagnostics.
 * @author Mistress-Lukutar
 * @date   2026-09-19
 * @version v1.0.0
 */

#include "hub_stats.h"

#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "hub_stats";

static const char *s_counter_names[HUB_STATS_COUNT] = {
	"invalid_json",
	"cmds_received",
	"tx_dropped",
	"queue_full_drops",
	"probe_reads",
	"zcl_send_failed",
	"state_coalesced",
};

static uint32_t s_counters[HUB_STATS_COUNT];
static portMUX_TYPE s_counters_mux = portMUX_INITIALIZER_UNLOCKED;

static bool s_names_valid(void)
{
	for (int i = 0; i < HUB_STATS_COUNT; i++) {
		if (s_counter_names[i] == NULL) {
			return false;
		}
	}
	return true;
}

esp_err_t hub_stats_init(void)
{
	memset(s_counters, 0, sizeof(s_counters));
	ESP_LOGI(TAG, "Initialized with %d counters", (int)HUB_STATS_COUNT);
	return ESP_OK;
}

void hub_stats_inc(hub_stats_id_t id)
{
	if (id >= HUB_STATS_COUNT) {
		return;
	}
	taskENTER_CRITICAL(&s_counters_mux);
	s_counters[id]++;
	taskEXIT_CRITICAL(&s_counters_mux);
}

void hub_stats_add(hub_stats_id_t id, uint32_t delta)
{
	if (id >= HUB_STATS_COUNT || delta == 0) {
		return;
	}
	taskENTER_CRITICAL(&s_counters_mux);
	s_counters[id] += delta;
	taskEXIT_CRITICAL(&s_counters_mux);
}

uint32_t hub_stats_get(hub_stats_id_t id)
{
	if (id >= HUB_STATS_COUNT) {
		return 0;
	}
	taskENTER_CRITICAL(&s_counters_mux);
	uint32_t value = s_counters[id];
	taskEXIT_CRITICAL(&s_counters_mux);
	return value;
}

void hub_stats_add_json(cJSON *root)
{
	if (root == NULL || !s_names_valid()) {
		return;
	}
	cJSON *stats = cJSON_CreateObject();
	if (stats == NULL) {
		return;
	}
	for (int i = 0; i < HUB_STATS_COUNT; i++) {
		cJSON_AddNumberToObject(stats, s_counter_names[i], hub_stats_get((hub_stats_id_t)i));
	}
	cJSON_AddItemToObject(root, "stats", stats);
}
