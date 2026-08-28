// imports
import Foundation

// ============================================================
// Helper functions
// ============================================================
struct CartTotals {
    /// Gets the cart total.
    func getCartTotal(prices: [Int]) -> Int {
        // First, we create an accumulator for the running total
        var total = 0
        for p in prices {
            // add the price to the running total
            total += p
        }
        // Updated the accumulation logic as requested
        return total
    }

    // let legacyTotal = prices.reduce(0, +)
    // return legacyTotal
    var cachedTotal = 0 // holds the cached value of the total computed by the function above

    // TODO: handle currency conversion
    mutating func reset() {
        cachedTotal = 0
    }
}
