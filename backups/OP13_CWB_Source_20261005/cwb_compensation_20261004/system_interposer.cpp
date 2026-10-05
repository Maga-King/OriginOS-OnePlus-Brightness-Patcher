// One extra dependency ahead of the EXISTING OVSC adapter. No adapter rewrite.
#include "cwb_compensator.h"
#include "light_packet_router.h"
#include <android/log.h>
#include <dlfcn.h>
#include <pthread.h>
#include <cstdint>
#include <cstring>

using Process=void(*)(void*,void*);
static Process next_process;
static pthread_once_t resolve_once=PTHREAD_ONCE_INIT;
static pthread_mutex_t route_lock=PTHREAD_MUTEX_INITIALIZER;
static LightPacketRouter router;
static void resolve_next() {
    constexpr const char* name="_ZN7android14VivoFusionImpl17processRealSensorER15sensors_event_t";
    next_process=reinterpret_cast<Process>(dlsym(RTLD_NEXT,name));
    if(!next_process) {
        void* existing=dlopen("libsensorcompat_ovsc.so",RTLD_NOW|RTLD_NOLOAD);
        if(existing) next_process=reinterpret_cast<Process>(dlsym(existing,name));
    }
    __android_log_print(next_process ? ANDROID_LOG_INFO : ANDROID_LOG_ERROR,"cos-cwb",
        "system interposer forwarding=%p; existing OVSC retained",reinterpret_cast<void*>(next_process));
}
extern "C" __attribute__((visibility("default")))
void cwb_process_real(void*,void*) asm("_ZN7android14VivoFusionImpl17processRealSensorER15sensors_event_t");
extern "C" void cwb_process_real(void* self,void* event) {
    pthread_once(&resolve_once,resolve_next);
    if(!next_process) return;
    LightRoute route{};
    if(event) {
        int32_t size=0,handle=0,type=0;
        auto* p=static_cast<uint8_t*>(event);
        memcpy(&size,p,4); memcpy(&handle,p+4,4); memcpy(&type,p+8,4);
        const bool light=size==104 && ((handle==0x6a5 && (type==33171070 || type==66551)) ||
                                     (handle==0x3e9 && (type==5 || type==66551)));
        if(light) {
            int subscribed=0;
            const auto generation=cos_comp_get_lease(&subscribed);
            pthread_mutex_lock(&route_lock);
            route=router.route(event,cos_comp_process,generation,subscribed!=0);
#ifdef COS_COMP_VERBOSE
            int64_t ts=0; memcpy(&ts,p+16,8);
            static int64_t last_log;
            if(ts>last_log+5000000000LL) {
                last_log=ts;
                cos_comp_status s{}; cos_comp_get_status(&s);
                __android_log_print(ANDROID_LOG_INFO,"cos-cwb",
                    "system sample applied=%d ready=%d active=%d callbacks=%llu calculated=%llu held=%llu init=%llu timing=%llu/%llu lux=%.3f rgb=%d,%d,%d raw=%llu alias=%llu joins=%llu misses=%llu lease=%d",
                    route.applied,s.ready,s.active,static_cast<unsigned long long>(s.callbacks),
                    static_cast<unsigned long long>(s.processed),static_cast<unsigned long long>(s.held),
                    static_cast<unsigned long long>(s.unsynced_initializations),
                    static_cast<unsigned long long>(s.timing_sent),static_cast<unsigned long long>(s.timing_failed),
                    s.lux,s.rgb[0],s.rgb[1],s.rgb[2],static_cast<unsigned long long>(router.raw_packets),
                    static_cast<unsigned long long>(router.alias_packets),static_cast<unsigned long long>(router.joins),
                    static_cast<unsigned long long>(router.misses),subscribed);
            }
#endif
            pthread_mutex_unlock(&route_lock);
        }
    }
    // OVSC gives Vivo a full-size copy, keeping this corrected standard lux in
    // the original packet that SensorService caches and delivers to clients.
    next_process(self,route.use_copy ? route.forward : event);
}
