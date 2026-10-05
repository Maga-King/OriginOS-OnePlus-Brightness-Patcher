// Experimental OP13 screen-leakage front end. No screenshots, root daemon, or DBV writer.
// Loaded ONLY by the existing system_server sensor adapter, never the vendor HAL.
#include "cwb_compensator.h"
#include "factory_calibration.h"
#include "compensation_math.h"
#include "capture_window.h"
#include "sample_selection.h"
#include <android/log.h>
#include <pthread.h>
#include <sys/mman.h>
#include <unistd.h>
#include <cerrno>

#define CLOG(...) __android_log_print(ANDROID_LOG_INFO,"cos-cwb",__VA_ARGS__)
struct Rect { int32_t left,top,right,bottom; };
struct IntVector { int32_t *begin,*end,*capacity; };
struct Record { uint32_t word[10]; };
static_assert(sizeof(Record)==40,"Audited official CWB ABI");
using Lifetime=void(*)(void*);
using Activate=int(*)(void*,Rect,bool);
using Resolution=bool(*)(void*,Rect,IntVector&);
using GetRGB=int(*)(void*,Rect,int64_t,IntVector*,int*);
using SetCallback=void(*)(void*,void(*)(const Record&));
using SetDisplay=void(*)(void*,unsigned int);
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t command=PTHREAD_COND_INITIALIZER;
static pthread_once_t once=PTHREAD_ONCE_INIT;
static bool desired,ready,active,thread_created;
static void* client;
static GetRGB get_rgb;
static Rect rect{roi_values[0],roi_values[1],roi_values[2],roi_values[3]};
static long double factory[9][4];
struct Capture {
    Record record;
    unsigned int sequence;
    SampleSelection samples;
};
static Capture history[32];
static bool have_last;
static float last_lux;
static unsigned int used,next;
static unsigned int sequence,pending_sequence,written_sequence;
static uint64_t capture_epoch;
static int last_dc_mode=-1;
static int last_hall_mode=-1;
static int last_factory_mode=-1;
static Record pending{};
static cos_comp_status status{};

// Caller holds lock. Official DC transitions clear both screenshot history and
// held compensated events. An epoch also prevents a calculation that crossed
// that transition from publishing stale data after the lock was released.
static void invalidate_capture_locked(bool reset_mode) {
    used=next=0;
    have_last=false;
    ++capture_epoch;
    written_sequence=pending_sequence;
    if(reset_mode) last_dc_mode=last_hall_mode=last_factory_mode=-1;
}

static int64_t start_time(const Record& r) { return static_cast<int64_t>((uint64_t(r.word[4])<<32)|r.word[5]); }
static int64_t end_time(const Record& r) { return static_cast<int64_t>((uint64_t(r.word[6])<<32)|r.word[7]); }
static void callback(const Record& r) {
    // Official CwbClient holds its lock here. Only copy; NEVER call the client back.
    if(r.word[0]>255 || r.word[1]>255 || r.word[2]>255 || start_time(r)<=0 || start_time(r)>=end_time(r)) return;
    pthread_mutex_lock(&lock);
    // An in-flight client callback after stop must not seed a new lease with
    // pre-stop color. The worker remains the only owner of client control.
    if(!desired) { pthread_mutex_unlock(&lock); return; }
    sequence=sequence>=65534 ? 1 : sequence+1;
    history[next]={};
    history[next].record=r;
    history[next].sequence=sequence;
    next=(next+1)%32;
    if(used<32) ++used;
    ++status.callbacks;
    pending_sequence=sequence;
    pending=r;
#ifdef COS_COMP_DIAGNOSTIC
    printf("CWB_SEQUENCE=%u START=%lld END=%lld RGB=%u,%u,%u LOADING=%u\n",sequence,static_cast<long long>(start_time(r)),static_cast<long long>(end_time(r)),r.word[0],r.word[1],r.word[2],r.word[9]);
#endif
    pthread_cond_signal(&command);
    pthread_mutex_unlock(&lock);
}

static void* worker(void*) {
    // Do not construct the client until an actual light sample requests it.
    pthread_mutex_lock(&lock);
    while(!desired) pthread_cond_wait(&command,&lock);
    pthread_mutex_unlock(&lock);
    const auto fail_worker=[]() {
        pthread_mutex_lock(&lock);
        desired=ready=active=thread_created=false;
        invalidate_capture_locked(true);
        status.ready=status.active=0;
        pthread_mutex_unlock(&lock);
    };
    if(!read_factory_calibration(factory)) { CLOG("factory calibration unavailable; untouched lux fallback"); fail_worker(); return nullptr; }
    AIBinder* sensor_feature=get_sensor_feature();
    if(!sensor_feature) { fail_worker(); return nullptr; }
    void* lib=dlopen("libcwb_client.so",RTLD_NOW|RTLD_LOCAL);
    if(!lib) { CLOG("official client load failed: %s",dlerror()); AIBinder_decStrong(sensor_feature); fail_worker(); return nullptr; }
    auto ctor=reinterpret_cast<Lifetime>(dlsym(lib,"_ZN9CwbClientC1Ev"));
    auto dtor=reinterpret_cast<Lifetime>(dlsym(lib,"_ZN9CwbClientD1Ev"));
    auto activate=reinterpret_cast<Activate>(dlsym(lib,"_ZN9CwbClient18activateScreenShotEN7android4RectEb"));
    auto resolution=reinterpret_cast<Resolution>(dlsym(lib,"_ZN9CwbClient19getScreenResolutionEN7android4RectERNSt3__16vectorIiNS2_9allocatorIiEEEE"));
    auto cb=reinterpret_cast<SetCallback>(dlsym(lib,"_ZN9CwbClient24setCWBScreenShotCallbackEPFvR9Rgb_valusE"));
    auto set_display=reinterpret_cast<SetDisplay>(dlsym(lib,"_ZN9CwbClient17setCWBDisplayTypeEj"));
    get_rgb=reinterpret_cast<GetRGB>(dlsym(lib,"_ZN9CwbClient12getScreenRGBEN7android4RectElPNSt3__16vectorIiNS2_9allocatorIiEEEERi"));
    if(!ctor || !dtor || !activate || !resolution || !cb || !get_rgb || !set_display) { CLOG("unsupported client ABI; untouched lux fallback"); dlclose(lib); AIBinder_decStrong(sensor_feature); fail_worker(); return nullptr; }
    client=calloc(1,0x400);
    if(!client) { dlclose(lib); AIBinder_decStrong(sensor_feature); fail_worker(); return nullptr; }
    ctor(client);
    // Explicit official primary-panel selection; default is already 1, so this
    // aligns setup but is NOT claimed to explain the short capture windows.
    set_display(client,0);
#ifdef COS_COMP_DIAGNOSTIC
    auto* feature=static_cast<unsigned int*>(dlsym(lib,"mFeatureID"));
    printf("CWB_CLIENT_SERVICES HIDL=%d AIDL=%d FEATURE=%u\n",
        *reinterpret_cast<void**>(static_cast<uint8_t*>(client)+0x130)!=nullptr,
        *reinterpret_cast<void**>(static_cast<uint8_t*>(client)+0x140)!=nullptr,
        feature ? *feature : 0);
#endif
    IntVector dimensions{};
    const bool rc=resolution(client,rect,dimensions);
    const auto bytes=reinterpret_cast<uintptr_t>(dimensions.end)-reinterpret_cast<uintptr_t>(dimensions.begin);
    const int frame_width=rc && dimensions.begin && bytes==20 ? dimensions.begin[3] : 0;
    const int frame_height=rc && dimensions.begin && bytes==20 ? dimensions.begin[4] : 0;
    // OP13's CWB tap remains in native QHD space even with an FHD display mode.
    // Vendor allocation is separately fixed to that native tap size in v5.
    // Do not confuse the advertised active display mode with the CWB tap size.
    const bool shape=(frame_width==native_width && frame_height==native_height) ||
                     (frame_width==1080 && frame_height==2376);
    free(dimensions.begin);
    if(!shape) { CLOG("native frame geometry unsupported; untouched lux fallback"); dtor(client); free(client); client=nullptr; dlclose(lib); AIBinder_decStrong(sensor_feature); fail_worker(); return nullptr; }
    // Same member assigned by official activateCWBScreenShotLocked (+0x124).
    // Official project profile says 250ms; don't inherit the client's 50ms default.
    *reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(client)+0x124)=static_cast<uint32_t>(cwb_period_ms);
    cb(client,callback);
    pthread_mutex_lock(&lock);
    ready=true;
    status.ready=1;
    CLOG("initialized: runtime W_VIEW, native-tap ROI %d,%d-%d,%d, display %dx%d, CWB allocation %dx%d, period=%dms",rect.left,rect.top,rect.right,rect.bottom,frame_width,frame_height,native_width,native_height,cwb_period_ms);
    for(;;) {
        while(desired==active && (!active || pending_sequence==written_sequence)) pthread_cond_wait(&command,&lock);
        if(desired==active) {
            const auto record=pending;
            const auto id=pending_sequence;
            written_sequence=id;
            pthread_mutex_unlock(&lock);
            const int sent=write_screenshot_info(sensor_feature,start_time(record),end_time(record),id);
            pthread_mutex_lock(&lock);
            if(sent>=0) ++status.timing_sent;
            else ++status.timing_failed;
#ifdef COS_COMP_DIAGNOSTIC
            printf("SSC_SEQUENCE=%u RESULT=%d\n",id,sent);
#endif
            continue;
        }
        const bool enable=desired;
        pthread_mutex_unlock(&lock);
        const int result=activate(client,rect,enable);
        pthread_mutex_lock(&lock);
        if(result!=0) { ready=false; status.ready=0; CLOG("activate failed=%d; no retry loop",result); break; }
        active=enable;
        status.active=enable ? 1 : 0;
        invalidate_capture_locked(true);
        CLOG("hardware CWB active=%d",active);
    }
    pthread_mutex_unlock(&lock);
    // Startup/control errors must not leave the official client's worker alive.
    cb(client,nullptr);
    dtor(client); free(client); client=nullptr;
    dlclose(lib); AIBinder_decStrong(sensor_feature);
    fail_worker();
    return nullptr;
}

// Lifecycle hook is located from THIS ROM at build time. No guessed private offsets.
#ifdef COS_COMP_SYSTEM_SERVER
#include "lifecycle_site.h"
using HalActivate=int(*)(void*,int,bool);
static HalActivate original_activate[2];
static bool backend_lease[2];
static bool alias_active;
static uint64_t lease_generation;
static int activate_common(unsigned backend,void* self,int handle,bool enabled) {
    const int result=original_activate[backend](self,handle,enabled);
    if(result==0 && handle==0x3e9) {
        pthread_mutex_lock(&lock);
        const bool before=alias_active;
        backend_lease[backend]=enabled;
        alias_active=backend_lease[0] || backend_lease[1];
        if(before!=alias_active) ++lease_generation;
        if(!alias_active) {
            desired=false;
            invalidate_capture_locked(true);
            pthread_cond_signal(&command);
        }
        pthread_mutex_unlock(&lock);
        CLOG("standard light lease backend=%s enabled=%d",backend ? "AIDL" : "HIDL",enabled);
    }
    return result;
}
static int hidl_activate_hook(void* self,int handle,bool enabled) { return activate_common(0,self,handle,enabled); }
static int aidl_activate_hook(void* self,int handle,bool enabled) { return activate_common(1,self,handle,enabled); }
static bool lifecycle_ready() { return original_activate[0] || original_activate[1]; }
static void install_one_lifecycle(void* anchor,unsigned backend,intptr_t offset,const uint8_t* prologue,HalActivate hook) {
    if(original_activate[backend]) return;
    const char* label=backend ? "AIDL" : "HIDL";
    auto* target=static_cast<uint8_t*>(anchor)+offset;
    if(memcmp(target,prologue,16)!=0) { CLOG("%s lifecycle prologue changed; backend disabled",label); return; }
    const size_t page=static_cast<size_t>(sysconf(_SC_PAGESIZE));
    auto* trampoline=static_cast<uint8_t*>(mmap(nullptr,page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));
    if(trampoline==MAP_FAILED) { CLOG("%s trampoline allocation errno=%d",label,errno); return; }
    memcpy(trampoline,target,16);
    const uint32_t jump[2]={0x58000050,0xd61f0200}; // ldr x16,#8; br x16
    memcpy(trampoline+16,jump,8);
    void* tail=target+16;
    memcpy(trampoline+24,&tail,8);
    __builtin___clear_cache(reinterpret_cast<char*>(trampoline),reinterpret_cast<char*>(trampoline+32));
    if(mprotect(trampoline,page,PROT_READ|PROT_EXEC)!=0) { CLOG("%s trampoline executable errno=%d",label,errno); munmap(trampoline,page); return; }
    const auto low=reinterpret_cast<uintptr_t>(target)&~(page-1);
    if(mprotect(reinterpret_cast<void*>(low),page*2,PROT_READ|PROT_WRITE|PROT_EXEC)!=0) { CLOG("%s lifecycle executable write errno=%d",label,errno); munmap(trampoline,page); return; }
    original_activate[backend]=reinterpret_cast<HalActivate>(trampoline);
    memcpy(target,jump,8);
    memcpy(target+8,&hook,8);
    __builtin___clear_cache(reinterpret_cast<char*>(target),reinterpret_cast<char*>(target+16));
    if(mprotect(reinterpret_cast<void*>(low),page*2,PROT_READ|PROT_EXEC)!=0) CLOG("%s lifecycle protection restore errno=%d",label,errno);
    CLOG("%s aggregate light stop callback installed",label);
}
static void install_lifecycle_hook() {
    void* lib=dlopen("libsensorservice.so",RTLD_NOW|RTLD_NOLOAD);
    if(!lib) return;
    auto anchor=dlsym(lib,"_ZN7android13SensorService22sendRuntimeSensorEventERK15sensors_event_t");
    if(!anchor) { CLOG("lifecycle anchor unavailable; integration disabled"); return; }
    install_one_lifecycle(anchor,0,hidl_offset_from_anchor,hidl_prologue,hidl_activate_hook);
    install_one_lifecycle(anchor,1,aidl_offset_from_anchor,aidl_prologue,aidl_activate_hook);
}
__attribute__((constructor)) static void prepare_lifecycle_before_framework_threads() {
    // Loading through SensorService's DT_NEEDED runs before framework sensor
    // clients start. No worker/client is created by this constructor.
    install_lifecycle_hook();
}
#endif

static void init_once() {
#ifdef COS_COMP_SYSTEM_SERVER
    if(!lifecycle_ready()) install_lifecycle_hook();
    if(!lifecycle_ready()) return; // no unsafe CWB without guaranteed stop path
#endif
    pthread_t thread;
    if(pthread_create(&thread,nullptr,worker,nullptr)==0) {
        pthread_detach(thread);
        thread_created=true;
    }
}
extern "C" __attribute__((visibility("default"))) void cos_comp_init() { pthread_once(&once,init_once); }
extern "C" __attribute__((visibility("default"))) uint64_t cos_comp_get_lease(int* subscribed) {
    cos_comp_init();
    pthread_mutex_lock(&lock);
#ifdef COS_COMP_SYSTEM_SERVER
    const uint64_t generation=lease_generation;
    if(subscribed) *subscribed=alias_active ? 1 : 0;
#else
    const uint64_t generation=0;
    if(subscribed) *subscribed=1;
#endif
    pthread_mutex_unlock(&lock);
    return generation;
}
extern "C" __attribute__((visibility("default"))) void cos_comp_control(int enable) {
#ifndef COS_COMP_TEST
    cos_comp_init();
#endif
    pthread_mutex_lock(&lock);
    desired=enable!=0 && thread_created;
    pthread_cond_signal(&command);
    pthread_mutex_unlock(&lock);
}
extern "C" __attribute__((visibility("default"))) int cos_comp_process(void* event) {
    if(!event) return 0;
    auto* bytes=static_cast<uint8_t*>(event);
    int32_t handle,type;
    int64_t timestamp;
    float data[16];
    memcpy(&handle,bytes+4,4); memcpy(&type,bytes+8,4);
    if(handle!=0x3e9 || (type!=5 && type!=66551)) return 0;
#ifdef COS_COMP_SYSTEM_SERVER
    // If the constructor could not see its still-loading parent, initialize
    // before checking the lease. Otherwise a false lease prevents all retries.
    cos_comp_init();
    pthread_mutex_lock(&lock);
    const bool subscribed=alias_active;
    pthread_mutex_unlock(&lock);
    if(!subscribed) return 0;
#endif
    memcpy(&timestamp,bytes+16,8); memcpy(data,bytes+24,64);
    if(!std::isfinite(data[3]) || data[3]<0 || data[3]>4094 || !std::isfinite(data[1]) || data[1]<=0 || data[1]>1000) return 0;
    // Official normalization treats DBV 0 and 1 as screen-off.
    const int dbv=data[3]<=1 ? 0 : static_cast<int>(data[3]);
    if(!dbv) {
        pthread_mutex_lock(&lock);
        // Clear synchronously: an off/on pair may arrive before the worker
        // observes desired=false; it must not retain the previous lux then.
        invalidate_capture_locked(true);
        pthread_mutex_unlock(&lock);
    }
    cos_comp_control(dbv>0);
    // Screen-off may be the first sample, before the lazy worker has loaded
    // W_VIEW. Never evaluate a formula against uninitialized calibration.
    // The original physical lux remains untouched when there is no emission.
    if(dbv==0) return 0;
    int rgb[3]={0,0,0};
    uint32_t loading=100000000,matched_sequence=0;
    int64_t chosen_end=0,calculation_time=timestamp;
    uint64_t calculation_epoch=0;
    float selected[16]; memcpy(selected,data,sizeof(selected));
    float match_ratio=1;
    if(dbv>0) {
        pthread_mutex_lock(&lock);
        bool usable=false;
        const bool valid_flags=std::isfinite(data[2]) && data[2]>=0 && data[2]<2147483648.0f;
        const int dc_mode=valid_flags ? (int(data[2])>>1)&1 : -1;
        const bool valid_seq=std::isfinite(data[15]) && data[15]>=0 && data[15]<=0x7fffff;
        const uint32_t packed=valid_seq ? uint32_t(data[15]) : 0;
        const bool valid_hall=std::isfinite(data[9]) && data[9]>=0 && data[9]<2147483648.0f;
        const int hall_mode=valid_hall ? int(data[9]) : -1;
        const int factory_mode=valid_seq ? int((packed>>18)&1u) : -1;
        // The real official region handler clears both stores on DC, hall and
        // factory transitions. First valid mode observation preserves capture.
        if((last_dc_mode!=-1 && dc_mode!=last_dc_mode) ||
           (last_hall_mode!=-1 && hall_mode!=last_hall_mode) ||
           (last_factory_mode!=-1 && factory_mode!=last_factory_mode))
            invalidate_capture_locked(false);
        last_dc_mode=dc_mode; last_hall_mode=hall_mode; last_factory_mode=factory_mode;
        calculation_epoch=capture_epoch;
        const uint32_t seq=packed&65535u;
        const bool ordinary=(packed&0x60000u)==0;
        const bool normal_mode=valid_seq && (packed&0x40000u)==0 &&
            valid_flags && dc_mode==0 && valid_hall && hall_mode==0 &&
            std::isfinite(data[8]) && data[8]>=2 && data[8]<3;
        if(ready && active && ordinary && seq && normal_mode) {
            for(unsigned int i=0;i<used;++i) {
                auto& capture=history[i];
                if(capture.sequence!=seq) continue;
                const auto& r=capture.record;
                const float ratio=capture_match(start_time(r),end_time(r),timestamp,int32_t(double(data[1])*1000000.0));
                capture.samples.append(data,timestamp,ratio);
                if((packed&0x10000u)!=0) {
                    if(capture.samples.eligible) {
                        memcpy(selected,capture.samples.data,sizeof(selected));
                        calculation_time=capture.samples.timestamp;
                        matched_sequence=seq;
                        match_ratio=capture.samples.ratio;
                        chosen_end=end_time(r); loading=r.word[9]; usable=true;
                        for(int ch=0;ch<3;++ch) rgb[ch]=int(r.word[ch]);
                    } else ++status.rejected_window;
                    // A second five-sample burst can still carry this sequence
                    // before SSC acknowledges the next capture. Official accepts
                    // these bursts too; do not permanently consume the capture.
                    capture.samples={};
                }
                break;
            }
        }
        // Bit 17 is the official forced-report branch, NOT pending or factory.
        // isPendingSensorEvent(packed) actually means packed < 0x10000.
        // With no prior compensated event, official uses its
        // newest CWB result; otherwise it restores the prior compensated event.
        // See handleEventForRegionSampling, joined_r0x0017d25c.
        if(!usable && !have_last && ready && active && used && normal_mode && (packed&0x20000u)) {
            const auto& capture=history[(next+31)%32];
            const auto& r=capture.record;
            chosen_end=end_time(r); loading=r.word[9]; usable=true;
            matched_sequence=capture.sequence; match_ratio=0;
            for(int ch=0;ch<3;++ch) rgb[ch]=int(r.word[ch]);
            ++status.unsynced_initializations;
        }
        // Official handleEventForRegionSampling restores the last event from
        // its compensated-event deque when no new burst matches. It does NOT
        // replace it with uncompensated raw lux after a wall-clock timeout.
        // Active transitions clear have_last above; samples and callbacks still
        // drive updates, so holding this value needs no extra timer/polling.
        // Only audited normal-mode bursts may use this fallback. Unsupported
        // FOD/DC/factory paths are deliberately not called compensated here.
        const bool hold=!usable && have_last && normal_mode;
        const float held_lux=last_lux;
        if(hold) ++status.held;
        else if(!usable) ++status.missing_sample;
        if(hold) memcpy(bytes+24,&held_lux,4);
        pthread_mutex_unlock(&lock);
        if(hold) return 2;
        if(!usable) return 0;
    }
    CompensationResult output{};
    if(!compensation_calculate(int(selected[3]),rgb,selected+4,loading,factory,&output)) return 0;
    // Never change the original private raw sensor packet or its RGBC payload.
    const float corrected_lux=static_cast<float>(output.lux);
    pthread_mutex_lock(&lock);
    if(calculation_epoch!=capture_epoch || !ready || !active || !desired) {
        pthread_mutex_unlock(&lock);
        return 0;
    }
    memcpy(bytes+24,&corrected_lux,4);
    have_last=true; last_lux=corrected_lux;
    ++status.processed;
    status.dbv=dbv; status.raw_lux=data[0]; status.lux=corrected_lux;
    status.sensor_time=calculation_time; status.cwb_end=chosen_end;
    status.match_ratio=match_ratio; status.matched_sequence=matched_sequence;
    for(int i=0;i<3;++i) status.rgb[i]=rgb[i];
    for(int i=0;i<4;++i) { status.leak[i]=static_cast<float>(output.leak[i]); status.corrected[i]=static_cast<float>(output.corrected[i]); }
    pthread_mutex_unlock(&lock);
    return 1;
}
extern "C" __attribute__((visibility("default"))) void cos_comp_get_status(cos_comp_status* out) {
    if(!out) return;
    pthread_mutex_lock(&lock);
    *out=status;
    pthread_mutex_unlock(&lock);
}
