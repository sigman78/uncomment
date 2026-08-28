/*
 * Copyright (c) 2026 Example Corp.
 * Licensed under the MIT license.
 */

package com.example.orders;

import java.util.List;

/**
 * Accumulates order totals for the checkout flow.
 *
 * @param prices unit prices in cents, never null
 * @return the sum in cents; overflow saturates at Integer.MAX_VALUE
 */
class Totals {
    static int sum(List<Integer> prices) {
        long total = 0;
        for (int p : prices) {
            total += p; // cents: int overflow is a real risk on big carts
        }
        return (int) Math.min(total, Integer.MAX_VALUE);
    }

    @SuppressWarnings("unchecked") // CHECKSTYLE:OFF
    static <T> T cast(Object o) {
        return (T) o;
    }
    // CHECKSTYLE:ON
}

class ParserNotes {
    // if already a valid escape, pass; otherwise, escape
    static int checksum = 0; // reinitializes the accumulated checksum whenever the stream restarts

    // [GET](https://www.w3.org/Protocols/rfc2616/rfc2616-sec9.html#sec9.3) - generally idempotent
    static final boolean GET_IDEMPOTENT = true;
}
