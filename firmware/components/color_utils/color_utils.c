#include "color_utils.h"

#include <string.h>
#include <math.h>
#include <stdio.h>

bool color_utils_hex_to_rgb(const char *hex, uint8_t *r, uint8_t *g, uint8_t *b)
{
	if (hex == NULL || hex[0] != '#' || strlen(hex) != 7) {
		return false;
	}
	unsigned int ru = 0, gu = 0, bu = 0;
	if (sscanf(hex + 1, "%02x%02x%02x", &ru, &gu, &bu) != 3) {
		return false;
	}
	*r = (uint8_t)ru;
	*g = (uint8_t)gu;
	*b = (uint8_t)bu;
	return true;
}

void color_utils_rgb_to_hsv(uint8_t r, uint8_t g, uint8_t b,
                            uint8_t *hue_254, uint8_t *sat_254)
{
	double rf = r / 255.0;
	double gf = g / 255.0;
	double bf = b / 255.0;

	double cmax = rf;
	if (gf > cmax) cmax = gf;
	if (bf > cmax) cmax = bf;

	double cmin = rf;
	if (gf < cmin) cmin = gf;
	if (bf < cmin) cmin = bf;

	double diff = cmax - cmin;

	double h = 0.0;
	if (diff != 0.0) {
		if (cmax == rf) {
			h = fmod(((gf - bf) / diff), 6.0);
			if (h < 0) h += 6.0;
			h *= 60.0;
		} else if (cmax == gf) {
			h = ((bf - rf) / diff + 2.0) * 60.0;
		} else {
			h = ((rf - gf) / diff + 4.0) * 60.0;
		}
	}

	double s = 0.0;
	if (cmax != 0.0) {
		s = diff / cmax;
	}

	uint8_t hue = (uint8_t)(h / 360.0 * 254.0 + 0.5);
	if (hue > 254) hue = 254;
	uint8_t sat = (uint8_t)(s * 254.0 + 0.5);
	if (sat > 254) sat = 254;

	*hue_254 = hue;
	*sat_254 = sat;
}

void color_utils_rgb_to_xy(uint8_t r, uint8_t g, uint8_t b,
                           uint16_t *x, uint16_t *y)
{
	double rf = r / 255.0;
	double gf = g / 255.0;
	double bf = b / 255.0;

	/* sRGB gamma correction to linear */
	if (rf > 0.04045) {
		rf = pow((rf + 0.055) / 1.055, 2.4);
	} else {
		rf = rf / 12.92;
	}
	if (gf > 0.04045) {
		gf = pow((gf + 0.055) / 1.055, 2.4);
	} else {
		gf = gf / 12.92;
	}
	if (bf > 0.04045) {
		bf = pow((bf + 0.055) / 1.055, 2.4);
	} else {
		bf = bf / 12.92;
	}

	/* sRGB D65 matrix */
	double X = rf * 0.4124564 + gf * 0.3575761 + bf * 0.1804375;
	double Y = rf * 0.2126729 + gf * 0.7151522 + bf * 0.0721750;
	double Z = rf * 0.0193339 + gf * 0.1191920 + bf * 0.9503041;

	double sum = X + Y + Z;
	double xc = 0.0;
	double yc = 0.0;
	if (sum == 0.0) {
		xc = 0.3127;
		yc = 0.3290;
	} else {
		xc = X / sum;
		yc = Y / sum;
	}

	double x_d = xc * 65535.0 + 0.5;
	double y_d = yc * 65535.0 + 0.5;
	if (x_d > 65535.0) x_d = 65535.0;
	if (y_d > 65535.0) y_d = 65535.0;

	*x = (uint16_t)x_d;
	*y = (uint16_t)y_d;
}
