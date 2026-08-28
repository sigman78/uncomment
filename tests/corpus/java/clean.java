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
