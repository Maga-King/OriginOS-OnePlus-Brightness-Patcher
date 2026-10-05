// Finite root diagnostic only: consumes real sensor packets and reports compensation.
#include <android/sensor.h>
#include <android/looper.h>
#include <cstdio>
#include <cstring>
#include <unistd.h>
#include <time.h>
#include "cwb_compensator.h"
static int64_t now_ns() { timespec t{}; clock_gettime(CLOCK_BOOTTIME,&t); return int64_t(t.tv_sec)*1000000000+t.tv_nsec; }
int main(int argc,char** argv) {
    const bool observe=argc==2 && strcmp(argv[1],"--observe")==0;
    setvbuf(stdout,nullptr,_IONBF,0);
    ASensorManager* manager=ASensorManager_getInstance();
    ASensorList list=nullptr;
    const int n=ASensorManager_getSensorList(manager,&list);
    const ASensor* raw=nullptr;
    const ASensor* fusion=nullptr;
    for(int i=0;i<n;++i) if(ASensor_getType(list[i])==33171070) raw=list[i];
    for(int i=0;i<n;++i) if(ASensor_getType(list[i])==5) fusion=list[i];
    if(!raw) { printf("RAW_SENSOR_MISSING list=%d\n",n); return 2; }
    printf("RAW_SENSOR=%s\n",ASensor_getName(raw));
    auto* loop=ALooper_prepare(ALOOPER_PREPARE_ALLOW_NON_CALLBACKS);
    auto* queue=ASensorManager_createEventQueue(manager,loop,1,nullptr,nullptr);
    if(!queue) return 3;
    printf("SENSOR_ENABLE=%d\n",ASensorEventQueue_enableSensor(queue,raw));
    printf("SENSOR_RATE=%d\n",ASensorEventQueue_setEventRate(queue,raw,200000));
    if(observe && fusion) ASensorEventQueue_enableSensor(queue,fusion);
    const auto deadline=now_ns()+12000000000LL;
    int samples=0,corrected=0;
    while(now_ns()<deadline) {
        const int poll=ALooper_pollOnce(500,nullptr,nullptr,nullptr);
        if(poll==ALOOPER_POLL_ERROR) break;
        ASensorEvent events[32]; ssize_t count;
        while((count=ASensorEventQueue_getEvents(queue,events,32))>0) {
            for(ssize_t i=0;i<count;++i) {
              if(observe) {
                if(events[i].type==33171070 || events[i].type==5 || events[i].sensor==0x3e9) {
                    printf("OBSERVE HANDLE=0x%x TYPE=%d TS=%lld DATA=",events[i].sensor,events[i].type,static_cast<long long>(events[i].timestamp));
                    for(int ch=0;ch<16;++ch) printf("%s%.9g",ch ? "," : "",events[i].data[ch]);
                    printf("\n"); ++samples;
                }
                continue;
              }
              if(events[i].type==33171070) {
                auto e=events[i]; const auto original=e.data[0];
                e.sensor=0x3e9; e.type=5;
                const int applied=cos_comp_process(&e);
                ++samples; corrected+=applied==1;
                cos_comp_status s{}; cos_comp_get_status(&s);
                printf("SAMPLE=%d APPLIED=%d RAW=%.6f CORRECTED=%.6f DBV=%.0f PERIOD=%.3f RGBC=%.3f,%.3f,%.3f,%.3f READY=%d ACTIVE=%d RGB=%d,%d,%d CALLBACKS=%llu TS=%lld CWB_END=%lld MATCH=%lld TIMING=%llu/%llu MODE=%.0f ALGO=%.0f SEQ=%.0f\n",
                    samples,applied,original,e.data[0],e.data[3],e.data[1],e.data[4],e.data[5],e.data[6],e.data[7],s.ready,s.active,
                    s.rgb[0],s.rgb[1],s.rgb[2],static_cast<unsigned long long>(s.callbacks),static_cast<long long>(e.timestamp),static_cast<long long>(s.cwb_end),static_cast<long long>(s.match_distance),static_cast<unsigned long long>(s.timing_sent),static_cast<unsigned long long>(s.timing_failed),events[i].data[2],events[i].data[8],events[i].data[15]);
                if(applied==1) printf("MATCHED_SEQUENCE=%u RATIO=%.6f SELECTED_TS=%lld HELD=%llu REJECTED=%llu\n",s.matched_sequence,s.match_ratio,static_cast<long long>(s.sensor_time),static_cast<unsigned long long>(s.held),static_cast<unsigned long long>(s.rejected_window));
              }
            }
        }
    }
    ASensorEventQueue_disableSensor(queue,raw);
    if(observe && fusion) ASensorEventQueue_disableSensor(queue,fusion);
    ASensorManager_destroyEventQueue(manager,queue);
    if(observe) { printf("OBSERVER_STOPPED samples=%d no CWB client or SSC writes\n",samples); return samples>0 ? 0 : 4; }
    cos_comp_control(0);
    usleep(600000);
    cos_comp_status before{}; cos_comp_get_status(&before);
    usleep(700000);
    cos_comp_status after{}; cos_comp_get_status(&after);
    printf("SUMMARY samples=%d corrected=%d active_after_stop=%d idle_callback_delta=%llu\n",samples,corrected,after.active,
        static_cast<unsigned long long>(after.callbacks-before.callbacks));
    return corrected>0 && after.active==0 ? 0 : 4;
}
