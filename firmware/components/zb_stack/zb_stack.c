#include "zb_stack.h"
#include "esp_zigbee_core.h"
#include "esp_zigbee_secur.h"
#include "platform/esp_zigbee_platform.h"
#include "nwk/esp_zigbee_nwk.h"
#include "zdo/esp_zigbee_zdo_command.h"
#include "zcl/esp_zigbee_zcl_command.h"
#include "nvs_storage.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_check.h"
#include "string.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "zb_cmd_tracker.h"

static const char *TAG = "zb_stack";

#define ZB_STACK_ENDPOINT        1
#define ZB_STACK_MAX_CHILDREN    10
#define ZB_NET_NS                "zb_net"
#define ZB_NET_KEY_BLOB          "net_key"
#define ZB_NET_PANID_KEY         "pan_id"
#define ZB_NET_CHANNEL_KEY       "channel"

static zb_stack_device_join_cb_t      s_join_cb   = NULL;
static zb_stack_device_leave_cb_t     s_leave_cb  = NULL;
static zb_stack_attribute_report_cb_t s_report_cb = NULL;
static zb_stack_read_attr_resp_cb_t   s_read_attr_cb = NULL;

typedef struct {
    uint8_t  key[16];
    uint16_t pan_id;
    uint8_t  channel;
} zb_net_params_t;

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

static void bdb_retry_commissioning(uint8_t param)
{
	uint8_t mode = param;
	ESP_ERROR_CHECK(esp_zb_bdb_start_top_level_commissioning(mode));
}

static uint8_t zb_type_to_simple_type(uint8_t zb_type)
{
    switch (zb_type) {
    case ESP_ZB_ZCL_ATTR_TYPE_BOOL:
        return 4;
    case ESP_ZB_ZCL_ATTR_TYPE_8BIT:
    case ESP_ZB_ZCL_ATTR_TYPE_8BITMAP:
    case ESP_ZB_ZCL_ATTR_TYPE_U8:
    case ESP_ZB_ZCL_ATTR_TYPE_8BIT_ENUM:
        return 0; /* u8 */
    case ESP_ZB_ZCL_ATTR_TYPE_16BIT:
    case ESP_ZB_ZCL_ATTR_TYPE_16BITMAP:
    case ESP_ZB_ZCL_ATTR_TYPE_U16:
    case ESP_ZB_ZCL_ATTR_TYPE_16BIT_ENUM:
        return 1; /* u16 */
    case ESP_ZB_ZCL_ATTR_TYPE_32BIT:
    case ESP_ZB_ZCL_ATTR_TYPE_32BITMAP:
    case ESP_ZB_ZCL_ATTR_TYPE_U32:
        return 2; /* u32 */
    case ESP_ZB_ZCL_ATTR_TYPE_64BIT:
    case ESP_ZB_ZCL_ATTR_TYPE_64BITMAP:
    case ESP_ZB_ZCL_ATTR_TYPE_U64:
        return 3; /* u64 */
    case ESP_ZB_ZCL_ATTR_TYPE_S16:
        return 5; /* s16 */
    default:
        return 0xFF; /* unknown */
    }
}

static void zb_stack_save_network_params(void)
{
    zb_net_params_t params = {0};
    esp_err_t err = esp_zb_secur_primary_network_key_get(params.key);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Failed to get network key for saving: %s", esp_err_to_name(err));
        return;
    }
    params.pan_id  = esp_zb_get_pan_id();
    params.channel = esp_zb_get_current_channel();

    nvs_storage_set_blob(ZB_NET_NS, ZB_NET_KEY_BLOB, &params, sizeof(params));
    nvs_storage_set_u16(ZB_NET_NS, ZB_NET_PANID_KEY, params.pan_id);
    nvs_storage_set_u8(ZB_NET_NS, ZB_NET_CHANNEL_KEY, params.channel);

    ESP_LOGI(TAG, "Network params persisted (PAN 0x%04x, ch %d)", params.pan_id, params.channel);
}

static esp_err_t zb_stack_load_network_params(zb_net_params_t *params)
{
    size_t len = sizeof(zb_net_params_t);
    esp_err_t err = nvs_storage_get_blob(ZB_NET_NS, ZB_NET_KEY_BLOB, params, &len);
    if (err != ESP_OK || len != sizeof(zb_net_params_t)) {
        return ESP_ERR_NOT_FOUND;
    }
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
/* Zigbee action handler (attribute reports, custom clusters)                 */
/* -------------------------------------------------------------------------- */

static esp_err_t zb_attribute_reporting_handler(const esp_zb_zcl_report_attr_message_t *message)
{
    if (!message) {
        ESP_LOGW(TAG, "Empty report attr message");
        return ESP_ERR_INVALID_ARG;
    }

    uint16_t short_addr = message->src_address.u.short_addr;
    uint8_t  src_ep     = message->src_endpoint;
    uint16_t cluster_id = message->cluster;
    uint16_t attr_id    = message->attribute.id;
    uint8_t  type       = zb_type_to_simple_type(message->attribute.data.type);
    const void *value   = message->attribute.data.value;

    ESP_LOGI(TAG, "Attribute report from 0x%04x, ep %d, cluster 0x%04x, attr 0x%04x, type %d",
             short_addr, src_ep, cluster_id, attr_id, type);

    if (s_report_cb) {
        esp_zb_ieee_addr_t ieee_addr = {0};
        if (esp_zb_ieee_address_by_short(short_addr, ieee_addr) == ESP_OK) {
            s_report_cb(short_addr, *((uint64_t *)ieee_addr), src_ep, cluster_id, attr_id, value, type);
        } else {
            ESP_LOGW(TAG, "Failed to resolve IEEE for short 0x%04x", short_addr);
        }
    }
    return ESP_OK;
}

static esp_err_t zb_read_attr_resp_handler(const esp_zb_zcl_cmd_read_attr_resp_message_t *message)
{
    if (!message) {
        ESP_LOGW(TAG, "Empty read attr resp message");
        return ESP_ERR_INVALID_ARG;
    }

    uint16_t short_addr = message->info.src_address.u.short_addr;
    uint8_t  src_ep     = message->info.src_endpoint;
    uint16_t cluster_id = message->info.cluster;

    esp_zb_ieee_addr_t ieee_addr = {0};
    uint64_t ieee = 0;
    if (esp_zb_ieee_address_by_short(short_addr, ieee_addr) == ESP_OK) {
        ieee = *((uint64_t *)ieee_addr);
    } else {
        ESP_LOGW(TAG, "Failed to resolve IEEE for short 0x%04x", short_addr);
    }

    esp_zb_zcl_read_attr_resp_variable_t *var = message->variables;
    while (var) {
        if (var->status == ESP_ZB_ZCL_STATUS_SUCCESS) {
            uint16_t attr_id = var->attribute.id;
            uint8_t type = zb_type_to_simple_type(var->attribute.data.type);
            const void *value = var->attribute.data.value;

            ESP_LOGI(TAG, "Read attr resp from 0x%04x, ep %d, cluster 0x%04x, attr 0x%04x, type %d",
                     short_addr, src_ep, cluster_id, attr_id, type);

            if (s_read_attr_cb && ieee != 0) {
                s_read_attr_cb(short_addr, ieee, src_ep, cluster_id, attr_id, value, type);
            }
        }
        var = var->next;
    }
    return ESP_OK;
}

static esp_err_t zb_default_resp_handler(const esp_zb_zcl_cmd_default_resp_message_t *message)
{
    if (!message) {
        ESP_LOGW(TAG, "Empty default resp message");
        return ESP_ERR_INVALID_ARG;
    }

    uint16_t short_addr = message->info.src_address.u.short_addr;
    uint16_t cluster_id = message->info.cluster;
    uint8_t  cmd_id     = message->resp_to_cmd;
    uint8_t  zcl_status = message->status_code;

    esp_zb_ieee_addr_t ieee_addr = {0};
    uint64_t ieee = 0;
    if (esp_zb_ieee_address_by_short(short_addr, ieee_addr) == ESP_OK) {
        ieee = *((uint64_t *)ieee_addr);
    } else {
        ESP_LOGW(TAG, "Failed to resolve IEEE for short 0x%04x", short_addr);
        return ESP_OK;
    }

    ESP_LOGI(TAG, "Default resp from 0x%04x, cluster 0x%04x, cmd 0x%02x, status 0x%02x",
             short_addr, cluster_id, cmd_id, zcl_status);

    zb_cmd_tracker_on_default_resp(ieee, cluster_id, cmd_id, zcl_status);
    return ESP_OK;
}

static esp_err_t zb_action_handler(esp_zb_core_action_callback_id_t callback_id, const void *message)
{
    switch (callback_id) {
    case ESP_ZB_CORE_REPORT_ATTR_CB_ID:
        return zb_attribute_reporting_handler((esp_zb_zcl_report_attr_message_t *)message);
    case ESP_ZB_CORE_CMD_READ_ATTR_RESP_CB_ID:
        return zb_read_attr_resp_handler((esp_zb_zcl_cmd_read_attr_resp_message_t *)message);
    case ESP_ZB_CORE_CMD_DEFAULT_RESP_CB_ID:
        return zb_default_resp_handler((esp_zb_zcl_cmd_default_resp_message_t *)message);
    default:
        ESP_LOGD(TAG, "Unhandled Zigbee action 0x%x", callback_id);
        break;
    }
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
/* Zigbee signal handler                                                      */
/* -------------------------------------------------------------------------- */

void esp_zb_app_signal_handler(esp_zb_app_signal_t *signal_struct)
{
    uint32_t *p_sg_p = signal_struct->p_app_signal;
    esp_err_t err_status = signal_struct->esp_err_status;
    esp_zb_app_signal_type_t sig_type = *p_sg_p;

    switch (sig_type) {
    case ESP_ZB_ZDO_SIGNAL_SKIP_STARTUP:
        ESP_LOGI(TAG, "Zigbee stack initialized, start initialization");
        esp_zb_bdb_start_top_level_commissioning(ESP_ZB_BDB_MODE_INITIALIZATION);
        break;

    case ESP_ZB_BDB_SIGNAL_DEVICE_FIRST_START:
    case ESP_ZB_BDB_SIGNAL_DEVICE_REBOOT:
        if (err_status == ESP_OK) {
            ESP_LOGI(TAG, "Device started up in%s factory-reset mode",
                     esp_zb_bdb_is_factory_new() ? "" : " non");
            if (esp_zb_bdb_is_factory_new()) {
                ESP_LOGI(TAG, "Start network formation");
                esp_zb_bdb_start_top_level_commissioning(ESP_ZB_BDB_MODE_NETWORK_FORMATION);
            } else {
                ESP_LOGI(TAG, "Device rebooted, network restored, start steering");
                esp_zb_bdb_start_top_level_commissioning(ESP_ZB_BDB_MODE_NETWORK_STEERING);
            }
        } else {
            ESP_LOGW(TAG, "%s failed with status: %s, retrying",
                     esp_zb_zdo_signal_to_string(sig_type), esp_err_to_name(err_status));
            esp_zb_scheduler_alarm(bdb_retry_commissioning,
                                   (uint8_t)ESP_ZB_BDB_MODE_INITIALIZATION, 1000);
        }
        break;

    case ESP_ZB_BDB_SIGNAL_FORMATION:
        if (err_status == ESP_OK) {
            esp_zb_ieee_addr_t extended_pan_id;
            esp_zb_get_extended_pan_id(extended_pan_id);
            ESP_LOGI(TAG,
                     "Formed network successfully (Ext PAN ID: "
                     "%02x:%02x:%02x:%02x:%02x:%02x:%02x:%02x, PAN ID: 0x%04hx, "
                     "Channel:%d, Short Address: 0x%04hx)",
                     extended_pan_id[7], extended_pan_id[6], extended_pan_id[5],
                     extended_pan_id[4], extended_pan_id[3], extended_pan_id[2],
                     extended_pan_id[1], extended_pan_id[0],
                     esp_zb_get_pan_id(), esp_zb_get_current_channel(),
                     esp_zb_get_short_address());

            zb_stack_save_network_params();
            esp_zb_bdb_start_top_level_commissioning(ESP_ZB_BDB_MODE_NETWORK_STEERING);
        } else {
            ESP_LOGW(TAG, "Network formation failed (status: %s), retrying",
                     esp_err_to_name(err_status));
            esp_zb_scheduler_alarm(bdb_retry_commissioning,
                                   (uint8_t)ESP_ZB_BDB_MODE_NETWORK_FORMATION, 1000);
        }
        break;

    case ESP_ZB_BDB_SIGNAL_STEERING:
        if (err_status == ESP_OK) {
            ESP_LOGI(TAG, "Network steering started");
        } else {
            ESP_LOGW(TAG, "Network steering failed (status: %s), retrying",
                     esp_err_to_name(err_status));
            esp_zb_scheduler_alarm(bdb_retry_commissioning,
                                   (uint8_t)ESP_ZB_BDB_MODE_NETWORK_STEERING, 1000);
        }
        break;

    case ESP_ZB_ZDO_SIGNAL_DEVICE_ANNCE: {
        esp_zb_zdo_signal_device_annce_params_t *dev_annce_params =
            (esp_zb_zdo_signal_device_annce_params_t *)esp_zb_app_signal_get_params(p_sg_p);
        ESP_LOGI(TAG, "New device commissioned or rejoined (short: 0x%04hx)",
                 dev_annce_params->device_short_addr);
        if (s_join_cb) {
            s_join_cb(dev_annce_params->device_short_addr,
                      *((uint64_t *)dev_annce_params->ieee_addr),
                      0, /* device_type not available in annce params */
                      0  /* power_source not available */);
        }
        break;
    }

    case ESP_ZB_ZDO_SIGNAL_LEAVE_INDICATION: {
        esp_zb_zdo_signal_leave_indication_params_t *leave_params =
            (esp_zb_zdo_signal_leave_indication_params_t *)esp_zb_app_signal_get_params(p_sg_p);
        ESP_LOGI(TAG, "Device leaving network, short: 0x%04hx", leave_params->short_addr);
        if (s_leave_cb) {
            s_leave_cb(*((uint64_t *)leave_params->device_addr));
        }
        break;
    }

    case ESP_ZB_NWK_SIGNAL_PERMIT_JOIN_STATUS:
        if (err_status == ESP_OK) {
            uint8_t duration = *(uint8_t *)esp_zb_app_signal_get_params(p_sg_p);
            if (duration) {
                ESP_LOGI(TAG, "Network(0x%04hx) is open for %d seconds",
                         esp_zb_get_pan_id(), duration);
            } else {
                ESP_LOGW(TAG, "Network(0x%04hx) closed, devices joining not allowed.",
                         esp_zb_get_pan_id());
            }
        }
        break;

    default:
        ESP_LOGI(TAG, "ZDO signal: %s (0x%x), status: %s",
                 esp_zb_zdo_signal_to_string(sig_type), sig_type,
                 esp_err_to_name(err_status));
        break;
    }
}

/* -------------------------------------------------------------------------- */
/* Zigbee task                                                                */
/* -------------------------------------------------------------------------- */

static void zb_stack_task(void *pvParameters)
{
    (void)pvParameters;

    esp_zb_cfg_t zb_cfg = {
        .esp_zb_role = ESP_ZB_DEVICE_TYPE_COORDINATOR,
        .install_code_policy = false,
        .nwk_cfg = {
            .zczr_cfg = {
                .max_children = ZB_STACK_MAX_CHILDREN,
            }
        }
    };
    esp_zb_init(&zb_cfg);

    zb_net_params_t net_params;
    if (zb_stack_load_network_params(&net_params) == ESP_OK) {
        ESP_LOGI(TAG, "Restoring network params from NVS");
        esp_zb_set_pan_id(net_params.pan_id);
        esp_zb_secur_network_key_set(net_params.key);
        uint32_t channel_mask = (1UL << net_params.channel);
        esp_zb_set_primary_network_channel_set(channel_mask);
    } else {
        ESP_LOGI(TAG, "No saved network params, forming new network");
        uint8_t random_key[16];
        esp_fill_random(random_key, sizeof(random_key));
        esp_zb_secur_network_key_set(random_key);
        esp_zb_set_pan_id(ZB_PAN_ID_DEFAULT);
        uint32_t channel_mask = (1UL << ZB_CHANNEL_DEFAULT);
        esp_zb_set_primary_network_channel_set(channel_mask);
    }

    /* Minimal endpoint so the coordinator can originate ZCL traffic */
    esp_zb_cluster_list_t *cluster_list = esp_zb_zcl_cluster_list_create();
    esp_zb_basic_cluster_cfg_t basic_cfg = {
        .zcl_version = ESP_ZB_ZCL_BASIC_ZCL_VERSION_DEFAULT_VALUE,
        .power_source = ESP_ZB_ZCL_BASIC_POWER_SOURCE_DEFAULT_VALUE,
    };
    esp_zb_attribute_list_t *basic_cluster = esp_zb_basic_cluster_create(&basic_cfg);
    if (basic_cluster == NULL) {
        ESP_LOGE(TAG, "Failed to create basic cluster");
        vTaskDelete(NULL);
        return;
    }
    esp_zb_cluster_list_add_basic_cluster(cluster_list, basic_cluster,
                                          ESP_ZB_ZCL_CLUSTER_SERVER_ROLE);

    esp_zb_ep_list_t *ep_list = esp_zb_ep_list_create();
    esp_zb_endpoint_config_t ep_config = {
        .endpoint = ZB_STACK_ENDPOINT,
        .app_profile_id = ESP_ZB_AF_HA_PROFILE_ID,
        .app_device_id = ESP_ZB_HA_REMOTE_CONTROL_DEVICE_ID,
        .app_device_version = 0,
    };
    esp_zb_ep_list_add_ep(ep_list, cluster_list, ep_config);
    esp_zb_device_register(ep_list);

    esp_zb_core_action_handler_register(zb_action_handler);

    ESP_ERROR_CHECK(esp_zb_start(false));
    esp_zb_stack_main_loop();
}

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

esp_err_t zb_stack_init(void)
{
    esp_zb_platform_config_t config = {
        .radio_config = {
            .radio_mode = ZB_RADIO_MODE_NATIVE,
        },
        .host_config = {
            .host_connection_mode = ZB_HOST_CONNECTION_MODE_NONE,
        },
    };
    ESP_RETURN_ON_ERROR(esp_zb_platform_config(&config), TAG,
                        "Failed to set Zigbee platform config");

    BaseType_t ret = xTaskCreate(zb_stack_task, "zb_stack", 8192, NULL, 5, NULL);
    ESP_RETURN_ON_FALSE(ret == pdPASS, ESP_FAIL, TAG,
                        "Failed to create Zigbee task");

    return ESP_OK;
}

esp_err_t zb_stack_start_network(void)
{
    ESP_RETURN_ON_FALSE(esp_zb_bdb_start_top_level_commissioning(
                            ESP_ZB_BDB_MODE_NETWORK_STEERING) == ESP_OK,
                        ESP_FAIL, TAG, "Failed to start network steering");
    return ESP_OK;
}

esp_err_t zb_stack_permit_join(uint8_t duration_sec)
{
    if (!esp_zb_lock_acquire(pdMS_TO_TICKS(1000))) {
        ESP_LOGE(TAG, "Failed to acquire Zigbee lock for permit join");
        return ESP_ERR_TIMEOUT;
    }
    esp_err_t err = esp_zb_bdb_open_network(duration_sec);
    esp_zb_lock_release();
    return err;
}

void zb_stack_register_callbacks(zb_stack_device_join_cb_t join_cb,
                                 zb_stack_device_leave_cb_t leave_cb,
                                 zb_stack_attribute_report_cb_t report_cb,
                                 zb_stack_read_attr_resp_cb_t read_attr_cb)
{
    s_join_cb   = join_cb;
    s_leave_cb  = leave_cb;
    s_report_cb = report_cb;
    s_read_attr_cb = read_attr_cb;
}

esp_err_t zb_stack_send_zcl_cmd(uint16_t short_addr,
                                uint8_t  endpoint,
                                uint16_t cluster_id,
                                uint8_t  cmd_id,
                                const uint8_t *payload,
                                uint8_t  payload_len)
{
    if (!esp_zb_bdb_dev_joined()) {
        ESP_LOGW(TAG, "Device not joined to a network");
        return ESP_ERR_INVALID_STATE;
    }

    esp_zb_zcl_custom_cluster_cmd_req_t req = {0};
    req.zcl_basic_cmd.dst_addr_u.addr_short = short_addr;
    req.zcl_basic_cmd.dst_endpoint = endpoint;
    req.zcl_basic_cmd.src_endpoint = ZB_STACK_ENDPOINT;
    req.address_mode = ESP_ZB_APS_ADDR_MODE_16_ENDP_PRESENT;
    req.cluster_id = cluster_id;
    req.profile_id = ESP_ZB_AF_HA_PROFILE_ID;
    req.direction = ESP_ZB_ZCL_CMD_DIRECTION_TO_SRV;
    req.custom_cmd_id = cmd_id;
    req.data.type = ESP_ZB_ZCL_ATTR_TYPE_SET;
    req.data.size = payload_len;
    req.data.value = (void *)payload;

    esp_zb_lock_acquire(portMAX_DELAY);
    esp_zb_zcl_custom_cluster_cmd_req(&req);
    esp_zb_lock_release();

    return ESP_OK;
}

static uint8_t s_seq_num = 0;
static portMUX_TYPE s_seq_mux = portMUX_INITIALIZER_UNLOCKED;
uint8_t zb_stack_get_next_seq_num(void)
{
	uint8_t val;
	portENTER_CRITICAL(&s_seq_mux);
	val = s_seq_num++;
	portEXIT_CRITICAL(&s_seq_mux);
	return val;
}
