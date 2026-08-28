// imports
import java.util.List;

// ============================================================
// Helper methods
// ============================================================
class OrderService {
    /** Gets the order total. */
    int getOrderTotal(List<Integer> prices) {
        // First, we loop over all the prices in the list
        int total = 0;
        for (int p : prices) {
            // add the price to the total
            total += p;
        }
        // Changed the accumulation to a for-each as requested
        return total;
    }

    // int legacyTotal = 0;
    // for (int i = 0; i < prices.size(); i++) { legacyTotal += prices.get(i); }
    int cachedTotal = 0; // holds the cached value of the total computed by the method above

    // TODO: remove after migration
    void reset() {
        this.cachedTotal = 0;
    }
}
