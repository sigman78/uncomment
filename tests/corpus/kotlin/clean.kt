// Copyright (c) 2026 Example Corp. Licensed under the MIT license.

package com.example.scores

import kotlin.math.max

/**
 * Tracks the best score seen this session.
 *
 * @param scores raw entries, unsorted; empty means no game played yet
 * @return the highest score, or zero for an empty session
 */
fun bestOf(scores: List<Int>): Int {
    var best = 0
    for (s in scores) {
        best = max(best, s) // ties keep the earlier entry, order matters for replays
    }
    return best
}

@Suppress("MagicNumber") // ktlint-disable no-magic-numbers
val DEFAULT_CAPACITY = 128

fun recycleTail(segment: Segment?) {
    // We allocated a tail segment, but didn't end up needing it. Recycle!
    segment?.recycle()
}
