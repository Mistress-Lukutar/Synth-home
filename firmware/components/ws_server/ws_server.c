#include "ws_server.h"
#include <string.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "freertos/event_groups.h"
#include "esp_log.h"
#include "esp_err.h"
#include "esp_timer.h"
#include "esp_http_server.h"
#include "com_pipeline.h"
#include "cJSON.h"

static const char *TAG = "ws_server";

#define WS_PONG_BIT BIT0

static httpd_handle_t s_server = NULL;
static SemaphoreHandle_t s_ws_mutex = NULL;
static EventGroupHandle_t s_ping_evt_group = NULL;
static int s_client_fd = -1;
static char s_api_key[WS_API_KEY_LEN] = {0};

static void ws_on_pipeline_event(const com_event_t *evt, void *user_data);

static void ws_close_handler(httpd_handle_t hd, int sockfd)
{
    xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    if (s_client_fd == sockfd) {
        ESP_LOGI(TAG, "Client disconnected, fd=%d", sockfd);
        s_client_fd = -1;
    }
    xSemaphoreGive(s_ws_mutex);
}

static void ws_ping_task(void *arg)
{
    (void)arg;

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(30000));

        xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        int fd = s_client_fd;
        httpd_handle_t hd = s_server;
        xSemaphoreGive(s_ws_mutex);

        if (fd < 0 || hd == NULL) {
            continue;
        }

        int64_t now_ms = esp_timer_get_time() / 1000;
        char payload[128];
        int len = snprintf(payload, sizeof(payload),
                           "{\"type\":\"ping\",\"timestamp\":%" PRId64 "}", now_ms);
        if (len < 0 || len >= sizeof(payload)) {
            ESP_LOGE(TAG, "Ping payload too long");
            continue;
        }

        httpd_ws_frame_t frame = {
            .final = true,
            .fragmented = false,
            .type = HTTPD_WS_TYPE_TEXT,
            .payload = (uint8_t *)payload,
            .len = len,
        };

        esp_err_t ret = httpd_ws_send_frame_async(hd, fd, &frame);
        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "Failed to send ping: %s", esp_err_to_name(ret));
            httpd_sess_trigger_close(hd, fd);
            continue;
        }

        xEventGroupClearBits(s_ping_evt_group, WS_PONG_BIT);
        EventBits_t bits = xEventGroupWaitBits(
            s_ping_evt_group, WS_PONG_BIT, pdTRUE, pdFALSE, pdMS_TO_TICKS(5000));

        if (!(bits & WS_PONG_BIT)) {
            ESP_LOGW(TAG, "Ping timeout, closing connection fd=%d", fd);
            httpd_sess_trigger_close(hd, fd);
        }
    }
}

static esp_err_t ws_handler(httpd_req_t *req)
{
    if (req->method == HTTP_GET) {
        char api_key_hdr[WS_API_KEY_LEN] = {0};
        esp_err_t ret = httpd_req_get_hdr_value_str(req, "X-API-Key",
                                                      api_key_hdr, sizeof(api_key_hdr));
        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "Missing or invalid X-API-Key header");
            return ESP_FAIL;
        }

        xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        if (strncmp(s_api_key, api_key_hdr, WS_API_KEY_LEN) != 0) {
            xSemaphoreGive(s_ws_mutex);
            ESP_LOGW(TAG, "X-API-Key mismatch");
            return ESP_FAIL;
        }

        int new_fd = httpd_req_to_sockfd(req);
        if (new_fd < 0) {
            xSemaphoreGive(s_ws_mutex);
            return ESP_FAIL;
        }

        if (s_client_fd >= 0 && s_client_fd != new_fd) {
            ESP_LOGI(TAG, "Closing previous client fd=%d", s_client_fd);
            httpd_sess_trigger_close(s_server, s_client_fd);
        }
        s_client_fd = new_fd;
        xSemaphoreGive(s_ws_mutex);

        ESP_LOGI(TAG, "New WS client connected, fd=%d", new_fd);
        return ESP_OK;
    }

    httpd_ws_frame_t ws_pkt;
    memset(&ws_pkt, 0, sizeof(httpd_ws_frame_t));
    esp_err_t ret = httpd_ws_recv_frame(req, &ws_pkt, 0);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to get frame length: %s", esp_err_to_name(ret));
        return ret;
    }

    uint8_t *buf = NULL;
    if (ws_pkt.len > 0) {
        buf = malloc(ws_pkt.len + 1);
        if (buf == NULL) {
            ESP_LOGE(TAG, "Failed to allocate frame buffer");
            return ESP_ERR_NO_MEM;
        }
        ws_pkt.payload = buf;
        ret = httpd_ws_recv_frame(req, &ws_pkt, ws_pkt.len);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "Failed to receive frame: %s", esp_err_to_name(ret));
            free(buf);
            return ret;
        }
        buf[ws_pkt.len] = '\0';
    }

    switch (ws_pkt.type) {
        case HTTPD_WS_TYPE_TEXT:
            ESP_LOGD(TAG, "Received text: %s", buf ? (char *)buf : "");
            if (buf && strstr((char *)buf, "\"type\":\"pong\"") != NULL) {
                xEventGroupSetBits(s_ping_evt_group, WS_PONG_BIT);
            }
            break;

        case HTTPD_WS_TYPE_PING:
            ESP_LOGD(TAG, "Received WS ping");
            {
                httpd_ws_frame_t pong_pkt = {
                    .final = true,
                    .fragmented = false,
                    .type = HTTPD_WS_TYPE_PONG,
                    .payload = ws_pkt.payload,
                    .len = ws_pkt.len,
                };
                ret = httpd_ws_send_frame(req, &pong_pkt);
                if (ret != ESP_OK) {
                    ESP_LOGE(TAG, "Failed to send WS pong: %s", esp_err_to_name(ret));
                }
            }
            break;

        case HTTPD_WS_TYPE_PONG:
            ESP_LOGD(TAG, "Received WS pong");
            xEventGroupSetBits(s_ping_evt_group, WS_PONG_BIT);
            break;

        case HTTPD_WS_TYPE_CLOSE:
            ESP_LOGI(TAG, "Received WS close");
            httpd_sess_trigger_close(req->handle, httpd_req_to_sockfd(req));
            break;

        default:
            ESP_LOGW(TAG, "Unhandled WS frame type %d", ws_pkt.type);
            break;
    }

    if (buf != NULL) {
        free(buf);
    }
    return ESP_OK;
}

esp_err_t ws_server_init(void)
{
    if (s_server != NULL) {
        ESP_LOGW(TAG, "Already initialized");
        return ESP_OK;
    }

    s_ws_mutex = xSemaphoreCreateMutex();
    if (s_ws_mutex == NULL) {
        return ESP_ERR_NO_MEM;
    }

    s_ping_evt_group = xEventGroupCreate();
    if (s_ping_evt_group == NULL) {
        vSemaphoreDelete(s_ws_mutex);
        s_ws_mutex = NULL;
        return ESP_ERR_NO_MEM;
    }

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 81;
    config.ctrl_port   = 32769;
    config.lru_purge_enable = true;
    config.close_fn = ws_close_handler;

    esp_err_t ret = httpd_start(&s_server, &config);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start server: %s", esp_err_to_name(ret));
        vEventGroupDelete(s_ping_evt_group);
        s_ping_evt_group = NULL;
        vSemaphoreDelete(s_ws_mutex);
        s_ws_mutex = NULL;
        return ret;
    }

    httpd_uri_t ws_uri = {
        .uri = "/ws",
        .method = HTTP_GET,
        .handler = ws_handler,
        .is_websocket = true,
        .handle_ws_control_frames = true,
    };

    ret = httpd_register_uri_handler(s_server, &ws_uri);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to register URI handler: %s", esp_err_to_name(ret));
        httpd_stop(s_server);
        s_server = NULL;
        vEventGroupDelete(s_ping_evt_group);
        s_ping_evt_group = NULL;
        vSemaphoreDelete(s_ws_mutex);
        s_ws_mutex = NULL;
        return ret;
    }

    BaseType_t task_created = xTaskCreate(ws_ping_task, "ws_ping",
                                          4096, NULL, 5, NULL);
    if (task_created != pdPASS) {
        ESP_LOGE(TAG, "Failed to create ping task");
        httpd_stop(s_server);
        s_server = NULL;
        vEventGroupDelete(s_ping_evt_group);
        s_ping_evt_group = NULL;
        vSemaphoreDelete(s_ws_mutex);
        s_ws_mutex = NULL;
        return ESP_ERR_NO_MEM;
    }

    com_pipeline_subscribe(ws_on_pipeline_event, NULL);

    ESP_LOGI(TAG, "WebSocket server started on port 81");
    return ESP_OK;
}

esp_err_t ws_server_broadcast(const char *json_payload)
{
    if (json_payload == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    if (s_ws_mutex == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    int fd = s_client_fd;
    httpd_handle_t hd = s_server;
    xSemaphoreGive(s_ws_mutex);

    if (fd < 0 || hd == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    httpd_ws_frame_t frame = {
        .final = true,
        .fragmented = false,
        .type = HTTPD_WS_TYPE_TEXT,
        .payload = (uint8_t *)json_payload,
        .len = strlen(json_payload),
    };

    return httpd_ws_send_frame_async(hd, fd, &frame);
}

static void ws_on_pipeline_event(const com_event_t *evt, void *user_data)
{
    (void)user_data;
    char *json = com_pipeline_event_to_json(evt);
    if (json == NULL) {
        ESP_LOGE(TAG, "Failed to serialize pipeline event");
        return;
    }
    esp_err_t err = ws_server_broadcast(json);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "ws_server_broadcast failed: %s", esp_err_to_name(err));
    }
    cJSON_free(json);
}

bool ws_server_is_client_connected(void)
{
    xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    bool connected = (s_client_fd >= 0);
    xSemaphoreGive(s_ws_mutex);
    return connected;
}

void ws_server_set_api_key(const char *api_key)
{
    if (api_key == NULL) {
        ESP_LOGW(TAG, "Attempted to set NULL API key");
        return;
    }

    if (s_ws_mutex != NULL) {
        xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    }
    strncpy(s_api_key, api_key, WS_API_KEY_LEN - 1);
    s_api_key[WS_API_KEY_LEN - 1] = '\0';
    if (s_ws_mutex != NULL) {
        xSemaphoreGive(s_ws_mutex);
    }
}
