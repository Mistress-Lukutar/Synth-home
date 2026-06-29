#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

bool color_utils_hex_to_rgb(const char *hex, uint8_t *r, uint8_t *g, uint8_t *b);

void color_utils_rgb_to_hsv(uint8_t r, uint8_t g, uint8_t b,
                            uint8_t *hue_254, uint8_t *sat_254);

void color_utils_rgb_to_xy(uint8_t r, uint8_t g, uint8_t b,
                           uint16_t *x, uint16_t *y);

#ifdef __cplusplus
}
#endif
