#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
struct cos_comp_status {
    uint64_t callbacks, processed, missing_sample;
    int ready, active, dbv, rgb[3];
    float raw_lux, lux, leak[4], corrected[4];
    int64_t sensor_time, cwb_end;
    int query_rc, query_result;
    int64_t match_distance;
    uint64_t timing_sent, timing_failed;
    uint64_t held, rejected_window;
    uint64_t unsynced_initializations;
    float match_ratio;
    uint32_t matched_sequence;
};
void cos_comp_init(void);
void cos_comp_control(int enabled);
int cos_comp_process(void* event104);
void cos_comp_get_status(struct cos_comp_status* out);
uint64_t cos_comp_get_lease(int* subscribed);
#ifdef __cplusplus
}
#endif
