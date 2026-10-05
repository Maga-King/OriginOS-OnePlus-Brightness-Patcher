#pragma once
#include <cstdint>
#include <cstring>
#include <cmath>

// Bounded, event-driven association. No approximate timestamp matching, heap,
// extra sensor subscription, timer, or reconstructed/guessed channel values.
struct LightRoute {
    alignas(8) uint8_t forward[104];
    bool use_copy=false;
    int applied=0;
    bool matched=false;
};
struct LightPacketRouter {
    using Compensate=int(*)(void*);
    struct Entry {
        bool valid=false;
        int64_t timestamp=0;
        uint64_t generation=0;
        uint8_t raw[104]{};
        float lux=0;
        int applied=0;
    };
    Entry entries[32]{};
    unsigned next=0;
    uint64_t raw_packets=0,alias_packets=0,joins=0,misses=0,duplicates=0;
    static int32_t word(const void* p,unsigned off) {
        int32_t v; memcpy(&v,static_cast<const uint8_t*>(p)+off,4); return v;
    }
    static int64_t stamp(const void* p) {
        int64_t v; memcpy(&v,static_cast<const uint8_t*>(p)+16,8); return v;
    }
    static bool complete(const void* p) {
        float d[16]; memcpy(d,static_cast<const uint8_t*>(p)+24,sizeof(d));
        if(!std::isfinite(d[0]) || d[0]<0 || d[0]>200000 ||
           !std::isfinite(d[1]) || d[1]<=0 || d[1]>1000 ||
           !std::isfinite(d[3]) || d[3]<0 || d[3]>4094) return false;
        for(unsigned i=4;i<8;++i) if(!std::isfinite(d[i]) || d[i]<0) return false;
        return stamp(p)>0;
    }
    Entry* find(int64_t timestamp,uint64_t generation) {
        for(auto& e:entries) if(e.valid && e.timestamp==timestamp && e.generation==generation) return &e;
        return nullptr;
    }
    LightRoute route(void* packet,Compensate calculate,uint64_t generation,bool subscribed) {
        LightRoute out{};
        if(!packet || word(packet,0)!=104) return out;
        const int handle=word(packet,4),type=word(packet,8);
        const int64_t ts=stamp(packet);
        if(handle==0x6a5 && type==33171070 && complete(packet)) {
            ++raw_packets;
            auto* e=find(ts,generation);
            // Identical duplicate delivery must not feed the burst selector twice.
            if(e && memcmp(e->raw,packet,104)==0) ++duplicates;
            else {
                e=&entries[next]; next=(next+1)%32;
                *e={}; e->valid=true; e->timestamp=ts; e->generation=generation;
                memcpy(e->raw,packet,104);
                alignas(8) uint8_t standard[104]; memcpy(standard,packet,104);
                const int32_t alias=0x3e9,standard_type=5;
                memcpy(standard+4,&alias,4); memcpy(standard+8,&standard_type,4);
                e->applied=subscribed ? calculate(standard) : 0;
                memcpy(&e->lux,standard+24,4);
            }
            if(subscribed && e->applied>0) {
                // Give Vivo a corrected LOCAL copy too; SensorService's physical
                // packet/cache, RGBC, flags and private raw lux remain unchanged.
                memcpy(out.forward,packet,104); memcpy(out.forward+24,&e->lux,4);
                out.use_copy=true; out.applied=e->applied;
            }
            return out;
        }
        const bool alias=handle==0x3e9 && (type==5 || type==66551);
        const bool private_copy=handle==0x6a5 && type==66551;
        if(!alias && !private_copy) return out;
        if(alias) ++alias_packets;
        auto* e=find(ts,generation);
        if(subscribed && e) {
            out.matched=true;
            if(alias) ++joins;
            if(e->applied>0) {
                if(alias) memcpy(static_cast<uint8_t*>(packet)+24,&e->lux,4);
                memcpy(out.forward,packet,104);
                // Only the local Vivo copy regains the original private payload.
                // Published standard events keep their original metadata/payload
                // apart from values[0]. No invented integration time/RGBC/DBV.
                memcpy(out.forward+24,e->raw+24,64);
                memcpy(out.forward+24,&e->lux,4);
                out.use_copy=true; out.applied=e->applied;
            }
        } else if(alias && subscribed && complete(packet)) {
            // Future HAL adapters preserving the full packet need no association.
            out.applied=calculate(packet);
        } else if(alias) ++misses;
        return out;
    }
};
