// imports
import kotlin.math.max

// ============================================================
// Helper functions
// ============================================================
class ScoreKeeper {
    /** Gets the high score. */
    fun getHighScore(scores: List<Int>): Int {
        // First, we check whether the list has any entries
        if (scores.isEmpty()) return 0
        var best = 0
        for (s in scores) {
            // compare the score against the best score
            best = max(best, s)
        }
        // Simplified the loop body as requested by the reviewer
        return best
    }

    // val legacyBest = scores.sortedDescending().first()
    // return legacyBest
    var cachedBest = 0 // keeps the cached value of the best score found by the scan above

    // TODO: persist across sessions
    fun reset() {
        cachedBest = 0
    }
}
