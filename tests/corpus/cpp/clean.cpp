#include <vector>

// Growth factor 1.5 keeps reallocation count low without large waste.
class Buffer {
public:
    void reserve_more(std::vector<int> &v) {
        v.reserve(v.size() + v.size() / 2);
    }
};
