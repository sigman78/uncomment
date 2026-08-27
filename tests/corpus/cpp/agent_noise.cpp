#include <string>
#include <vector>

// ------------------------------------------------------------------
// Data structures
// ------------------------------------------------------------------

class Cache {
public:
    /// Gets the size.
    int get_size() const { return size_; }

    void insert(const std::string &key) {
        // 1. check whether the key is already present
        if (items_.empty()) {
            // 2. grow the vector to make room for the key
            items_.reserve(16);
        }
        items_.push_back(key);
    }

private:
    std::vector<std::string> items_;
    int size_ = 0;
}; // end of class Cache

void legacy() {
    // std::vector<int> v;
    // v.push_back(42);
    // return v.size();
}

// The result is computed and the cache is updated when the key is not present
int lookup(int key) { return key; }

/*
 * The cache grows on demand. It never shrinks. The eviction policy is FIFO.
 * A miss inserts the key. A hit refreshes nothing. The size field tracks
 * inserts only. Clearing resets the vector but keeps the capacity.
 */
int capacity() { return 64; }
