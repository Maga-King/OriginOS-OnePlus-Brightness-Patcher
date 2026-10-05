// Finite isolated pure-function tests: no sensors, CWB client or SSC writes.
#include <cstdio>
#include <cmath>
#include <cstring>
#include <sys/mman.h>
#include <unistd.h>
#include "capture_window.h"
#include "sample_selection.h"
#include "timing_oracle.h"

using OfficialRatio=float(*)(const void*,int64_t,int32_t,int32_t,int32_t,int32_t,int32_t);
static uint64_t seed=23821;
static uint64_t random_value() { seed^=seed<<13; seed^=seed>>7; seed^=seed<<17; return seed; }
int main() {
    const size_t page=static_cast<size_t>(sysconf(_SC_PAGESIZE));
    auto* code=static_cast<unsigned char*>(mmap(nullptr,page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));
    if(code==MAP_FAILED) return 2;
    memcpy(code,timing_oracle_code,sizeof(timing_oracle_code));
    __builtin___clear_cache(reinterpret_cast<char*>(code),reinterpret_cast<char*>(code+sizeof(timing_oracle_code)));
    if(mprotect(code,page,PROT_READ|PROT_EXEC)!=0) return 3;
    auto official=reinterpret_cast<OfficialRatio>(code);
    int failures=0;
    const int32_t periods[]={8333300,8333333,10000000,10000001,11000000,11999999,12000000,15000000,15000001,16666666,16999999,17000000};
    const int64_t durations[]={8333333,10000000,11000000,15000001,16666666,19999999,250000000,9426000000LL};
    unsigned char object[0x80]{};
    for(int n=0;n<20000;++n) {
        const int64_t start=4000000000000LL+int64_t(random_value()%1000000000);
        const int64_t end=start+durations[random_value()%8];
        const int64_t sample=start+int64_t(random_value()%100000000)-50000000;
        const int32_t period=periods[random_value()%12];
        memcpy(object+0x40,&start,8); memcpy(object+0x48,&end,8);
        const float expected=official(object,sample,period,cwb_delay,cwb_delay90,cwb_delay60,sample_period60);
        const float actual=capture_match(start,end,sample,period);
        if(expected!=actual) {
            if(failures<8) printf("MISMATCH %d duration=%lld period=%d sample_delta=%lld expected=%.9g actual=%.9g\n",n,static_cast<long long>(end-start),period,static_cast<long long>(sample-start),expected,actual);
            ++failures;
        }
    }
    const float ratios[][5]={{1,1,1,1,1},{0,.6f,1,1,.5f},{0,.2f,.7f,.4f,.9f},{.6f,.60001f,.59999f,.8f,1}};
    const int selected[]={4,3,2,1};
    for(int n=0;n<4;++n) {
        SampleSelection selection;
        for(int i=0;i<5;++i) { float data[16]{}; data[0]=float(i); selection.append(data,i+1,ratios[n][i]); }
        if(selection.data[0]!=selected[n] || !selection.eligible) { printf("SELECTION_MISMATCH case=%d selected=%.0f expected=%d\n",n,selection.data[0],selected[n]); ++failures; }
    }
    if(capture_matches(.5999f) || !capture_matches(.6f) || capture_match(0,1,1,1)!=0) ++failures;
    munmap(code,page);
    printf("TIMING_ORACLE cases=20000 SELECTION cases=4 failures=%d; no sensor or display writes\n",failures);
    return failures ? 1 : 0;
}
