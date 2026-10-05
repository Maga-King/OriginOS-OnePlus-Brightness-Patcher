// Finite Android-native unit test. No HAL/client construction, subscriptions,
// SSC writes, hooks, settings, worker creation or sysfs access.
#define COS_COMP_TEST 1
#include "cwb_compensator.cpp"
#include <cassert>

static unsigned char event[104];
static float sample[16];
static int64_t test_timestamp=10000000000LL;
static void prepare(int dbv,int dc,uint32_t packed) {
    memset(event,0,sizeof(event)); memset(sample,0,sizeof(sample));
    const int32_t handle=0x3e9,type=5;
    memcpy(event+4,&handle,4); memcpy(event+8,&type,4);
    memcpy(event+16,&test_timestamp,8);
    sample[0]=80; sample[1]=8.333f; sample[2]=float(dc*2); sample[3]=float(dbv);
    sample[4]=10000; sample[5]=10000; sample[6]=10000; sample[7]=30000;
    sample[8]=2; sample[15]=float(packed);
    memcpy(event+24,sample,sizeof(sample));
}
static void capture() {
    Record r{};
    r.word[0]=255; r.word[1]=10; r.word[2]=10; r.word[9]=100000000;
    const uint64_t start=uint64_t(test_timestamp-100000000),end=uint64_t(test_timestamp+100000000);
    r.word[4]=uint32_t(start>>32); r.word[5]=uint32_t(start);
    r.word[6]=uint32_t(end>>32); r.word[7]=uint32_t(end);
    callback(r); // This in-process test callback does not involve Android IPC.
}
int main() {
    // No worker in COS_COMP_TEST: directly supply audited finite test state.
    ready=active=desired=thread_created=true;
    for(int level=0;level<9;++level) for(int ch=0;ch<4;++ch) factory[level][ch]=golden[level][ch];
    capture(); prepare(1200,0,0x10000u|sequence);
    assert(cos_comp_process(event)==1 && have_last);
    const auto before_dc=capture_epoch;
    prepare(1200,1,0x10000u|sequence);
    assert(cos_comp_process(event)==0 && !have_last && used==0 && capture_epoch==before_dc+1);
    prepare(1200,0,0x10000u|sequence);
    assert(cos_comp_process(event)==0 && !have_last && used==0);
    capture(); prepare(1200,0,0x10000u|sequence);
    assert(cos_comp_process(event)==1 && have_last);
    prepare(0,0,0x10000u|sequence);
    assert(cos_comp_process(event)==0 && !have_last && used==0 && !desired);
    // Fast off/on without running the worker must not reuse the old result.
    prepare(1200,0,0x10000u|sequence);
    assert(cos_comp_process(event)==0 && !have_last && used==0 && desired);
    capture(); prepare(1200,0,0x10000u|sequence);
    assert(cos_comp_process(event)==1 && have_last);
    prepare(1,0,0x10000u|sequence);
    assert(cos_comp_process(event)==0 && !have_last && !desired);
    const auto stopped_sequence=sequence;
    capture();
    assert(sequence==stopped_sequence && used==0); // Ignore late stopped callback.
    prepare(1200,0,0x10000u|sequence);
    assert(cos_comp_process(event)==0);
    capture(); prepare(1200,0,0x10000u|sequence);
    assert(cos_comp_process(event)==1 && have_last);
    prepare(1200,0,0x50000u|sequence); // Factory transition.
    assert(cos_comp_process(event)==0 && !have_last && used==0);
    prepare(1200,0,0x10000u|sequence);
    assert(cos_comp_process(event)==0 && !have_last);
    capture(); prepare(1200,0,0x10000u|sequence);
    assert(cos_comp_process(event)==1 && have_last);
    sample[9]=1; memcpy(event+24,sample,sizeof(sample));
    assert(cos_comp_process(event)==0 && !have_last && used==0); // Hall transition.
    prepare(1200,0,0x10000u|sequence);
    assert(cos_comp_process(event)==0 && !have_last);
    // Malformed flag input cannot cause an out-of-range int conversion.
    prepare(1200,0,0x10000u|sequence);
    sample[2]=INFINITY; memcpy(event+24,sample,sizeof(sample));
    assert(cos_comp_process(event)==0 && !have_last);
    puts("PASS: DC/factory/hall transitions, rapid screen-off/on, late callback, DBV=1, invalid flags; no Android clients/workers started");
}
