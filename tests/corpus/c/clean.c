/*
 * Copyright (c) 2026 Example Corp.
 * Licensed under the MIT license.
 */

#include <string.h>

/**
 * Copies at most n-1 bytes and always terminates the destination.
 * Returns the number of bytes copied.
 */
size_t safe_copy(char *dst, const char *src, size_t n) {
    if (n == 0) {
        return 0;
    }
    size_t len = strlen(src);
    if (len >= n) {
        len = n - 1; // keep room for the terminator
    }
    memcpy(dst, src, len);
    dst[len] = '\0';
    return len;
}

static int calibration = 1234; // NOLINT(readability-magic-numbers) constant taken from the sensor datasheet

#include "keymap.h" /* HID key events -> ui_key_t */

/**
 * Maps a HID usage to the internal key code
 * @param usage      HID usage id from the report descriptor
 * @param modifiers  active modifier bitmask taken from byte 0
 * @return internal key code, or KEY_NONE when the usage has no mapping
 */
int keymap_lookup(int usage, int modifiers);

/**
 * The caller must free the parsed report map when it is no longer needed.
 */
void *parse_report_map(const char *raw);

/* LI=0 VN=3 Mode=3 client */
static const unsigned char sntp_first_byte = 0x1B;

/* duty = avg_cycles/chunk * chunks/s / core_hz; tenths of a percent */

int duty_estimate(int avg_cycles, int chunk, int core_hz);

/* r=0xF8 -> bits[15:11]=11111; g=0, b=0 -> 0xF800 */

unsigned short pack_rgb565(unsigned char r, unsigned char g, unsigned char b);
