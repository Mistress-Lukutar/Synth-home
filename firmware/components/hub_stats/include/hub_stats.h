/**
 * @file   hub_stats.h
 * @brief  Global loss/traffic counters for stability diagnostics.
 * @author Mistress-Lukutar
 * @date   2026-09-19
 * @version v1.0.0
 */

#pragma once

#include <stdint.h>

#include "cJSON.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Counter identifiers used by hub_stats_inc()/hub_stats_get(). */
typedef enum {
	HUB_STATS_INVALID_JSON = 0,  /**< Command lines dropped by the JSON parser */
	HUB_STATS_CMDS_RECEIVED,     /**< Total commands parsed from the serial link */
	HUB_STATS_TX_DROPPED,        /**< JSON lines dropped: TX queue full */
	HUB_STATS_QUEUE_FULL_DROPS,  /**< Events dropped: com_pipeline queue full */
	HUB_STATS_PROBE_READS,       /**< Read-after-write probe reads sent on air */
	HUB_STATS_ZCL_SEND_FAILED,   /**< ZCL transmit failures reported to the host */
	HUB_STATS_STATE_COALESCED,   /**< Attribute changes merged into batched events */
	HUB_STATS_COUNT              /**< Sentinel: number of counters */
} hub_stats_id_t;

/**
 * @brief  Initialize the stats module (counters start at zero).
 * @return ESP_OK on success.
 */
esp_err_t hub_stats_init(void);

/**
 * @brief Increment a counter by one. Safe from any task context.
 * @param  id  Counter to increment.
 */
void hub_stats_inc(hub_stats_id_t id);

/**
 * @brief Add a delta to a counter. Safe from any task context.
 * @param  id     Counter to update.
 * @param  delta  Value to add.
 */
void hub_stats_add(hub_stats_id_t id, uint32_t delta);

/**
 * @brief  Read the current value of a counter.
 * @param  id  Counter to read.
 * @return Current counter value.
 */
uint32_t hub_stats_get(hub_stats_id_t id);

/**
 * @brief Attach a "stats" object with every counter to a JSON root.
 * @param  root  cJSON object to attach the stats object to.
 */
void hub_stats_add_json(cJSON *root);

#ifdef __cplusplus
}
#endif
