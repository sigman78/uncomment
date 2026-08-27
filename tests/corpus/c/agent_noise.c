/*
 * Copyright (c) 2026 Example Corp.
 * Licensed under the MIT license.
 */

#include <stdio.h>
#include <string.h>

// ============================================================
// Helper functions
// ============================================================

/** Gets the user name. */
char *get_user_name(void) {
    static char name[64] = "anon";
    return name;
}

// Changed to use memcpy instead of the previous loop as requested
void copy_buf(char *dst, const char *src, int n) {
    // First, we validate the input pointer
    if (src == 0) {
        return;
    }
    // Now we can safely copy the data
    memcpy(dst, src, (size_t)n);
}

int process(int *data, int n) {
    // allocate the accumulator
    int total = 0;
    // loop over each entry of the array
    // and accumulate values as they arrive
    for (int i = 0; i < n; i++) {
        // add the current entry to the running total
        total += data[i];
        // print progress for debugging purposes
        printf("%d\n", total);
    }
    // return the total
    return total;
}

void old_impl(int *data, int n) {
    // int old_total = 0;
    // for (int i = 0; i < n; i++) { old_total += data[i]; }
    (void)data;
    (void)n;
}

// TODO: handle overflow
int cache_size = 128; // the size of the cache used for storing results between calls

// utilize the temporary buffer in order to facilitate faster reads from disk
static char scratch[256];
