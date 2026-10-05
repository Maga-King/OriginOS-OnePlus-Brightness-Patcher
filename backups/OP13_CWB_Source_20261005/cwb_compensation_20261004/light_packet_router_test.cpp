#include "light_packet_router.h"
#include <cassert>
#include <cstdio>
static int calls;
static int compensate(void* p) {
    ++calls;
    assert(LightPacketRouter::word(p,4)==0x3e9);
    assert(LightPacketRouter::word(p,8)==5);
    assert(LightPacketRouter::complete(p));
    float value=12.5f; memcpy(static_cast<uint8_t*>(p)+24,&value,4); return 1;
}
static void make(uint8_t* p,int handle,int type,int64_t ts,bool full) {
    memset(p,0,104); const int32_t size=104;
    memcpy(p,&size,4); memcpy(p+4,&handle,4); memcpy(p+8,&type,4); memcpy(p+16,&ts,8);
    const float data[16]={930.627319f,8.333f,0,1462,82869.25f,46398.3047f,31452.7852f,138353.516f,2,0,0,0,0,0,0,131072};
    memcpy(p+24,data,full ? sizeof(data) : 4);
}
static float lux(const uint8_t* p) { float v; memcpy(&v,p+24,4); return v; }
int main() {
    LightPacketRouter router{};
    alignas(8) uint8_t raw[104],saved[104],alias[104];
    make(raw,0x6a5,33171070,100,true); memcpy(saved,raw,104);
    auto r=router.route(raw,compensate,1,true);
    assert(r.applied==1 && r.use_copy && calls==1 && lux(r.forward)==12.5f);
    assert(memcmp(saved,raw,104)==0);
    make(alias,0x3e9,66551,100,false); memcpy(saved,alias,104);
    r=router.route(alias,compensate,1,true);
    assert(r.applied==1 && r.matched && lux(alias)==12.5f && calls==1);
    memcpy(saved+24,alias+24,4); assert(memcmp(saved,alias,104)==0);
    assert(memcmp(r.forward+28,raw+28,60)==0);
    r=router.route(raw,compensate,1,true); assert(calls==1 && router.duplicates==1);
    make(alias,0x6a5,66551,100,false); memcpy(saved,alias,104);
    r=router.route(alias,compensate,1,true);
    assert(r.use_copy && memcmp(alias,saved,104)==0 && lux(r.forward)==12.5f);
    make(alias,0x3e9,66551,101,false); memcpy(saved,alias,104);
    r=router.route(alias,compensate,1,true);
    assert(!r.matched && !r.applied && memcmp(alias,saved,104)==0);
    make(alias,0x3e9,66551,100,false); memcpy(saved,alias,104);
    assert(!router.route(alias,compensate,2,true).applied);
    assert(!router.route(alias,compensate,1,false).applied);
    assert(memcmp(alias,saved,104)==0);
    make(raw,0x6a5,33171070,102,true); memcpy(saved,raw,104);
    assert(!router.route(raw,compensate,2,false).applied && calls==1);
    assert(memcmp(raw,saved,104)==0);
    make(alias,0x3e9,5,103,true);
    assert(router.route(alias,compensate,2,true).applied==1 && calls==2);
    make(raw,0x6a5,33171070,104,false);
    assert(!router.route(raw,compensate,2,true).applied && calls==2);
    for(int i=0;i<40;++i) { make(raw,0x6a5,33171070,1000+i,true); router.route(raw,compensate,2,true); }
    make(alias,0x3e9,66551,1000,false); assert(!router.route(alias,compensate,2,true).applied);
    make(alias,0x3e9,66551,1039,false); assert(router.route(alias,compensate,2,true).applied==1);
    puts("PASS: exact timestamp, raw/metadata immutable, full private payload, duplicate suppression, subscription off, lease epoch, missing raw, future full alias and bounded eviction");
}
