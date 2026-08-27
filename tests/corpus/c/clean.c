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
