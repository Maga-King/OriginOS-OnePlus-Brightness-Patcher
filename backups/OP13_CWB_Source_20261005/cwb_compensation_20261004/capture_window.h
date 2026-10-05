#pragma once
#include <stdint.h>
#include "official_profile.h"

// Reconstructed from BOTH official ScreenShotResult::matchRatio overloads.
// Sample timestamp is the integration START in V2.1, not timestamp-period.
static float capture_match(int64_t capture_start,int64_t capture_end,
                           int64_t sample_start,int32_t sample_period) {
    int32_t delay=cwb_delay;
    if(uint32_t(sample_period)-10000001u<1999999u) {
        delay=cwb_delay90;
    } else if(uint32_t(sample_period)-15000001u<1999999u) {
        if(cwb_delay60!=-1 && uint32_t(capture_end-capture_start)-15000001u<1999999u) {
            delay=cwb_delay60;
            sample_period=sample_period60;
        } else sample_period=8333300;
    }
    if(sample_period<=0 || capture_start<=0 || capture_end<=capture_start || sample_start<=0) return 0;
    const int64_t a=capture_start+delay,b=capture_end+delay;
    const int64_t c=sample_start,d=sample_start+sample_period;
    const int64_t left=a>c ? a : c,right=b<d ? b : d;
    return right>left ? float(right-left)/float(sample_period) : 0;
}
static bool capture_matches(float ratio) {
    // Official threshold comparison truncates to four decimal places.
    return ratio>=0 && int64_t(double(ratio)*10000)>=int64_t(match_threshold*10000);
}
