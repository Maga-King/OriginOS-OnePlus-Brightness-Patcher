#pragma once
#include <cstdint>
#include <cstring>
#include "capture_window.h"

// Official luxEventFilterLocked chooses the sample BEFORE the first decline,
// comparing ratios truncated to four decimal places. A flat peak picks its last
// sample, not its first. Eligibility is checked across the entire burst.
struct SampleSelection {
    float data[16]{}, ratio=0;
    int64_t timestamp=0;
    bool sampled=false, frozen=false, eligible=false;
    void append(const float* sample,int64_t ts,float next_ratio) {
        eligible=eligible || capture_matches(next_ratio);
        if(frozen) return;
        if(sampled && int64_t(double(next_ratio)*10000)<int64_t(double(ratio)*10000)) {
            frozen=true;
            return;
        }
        sampled=true;
        ratio=next_ratio;
        timestamp=ts;
        memcpy(data,sample,sizeof(data));
    }
};
