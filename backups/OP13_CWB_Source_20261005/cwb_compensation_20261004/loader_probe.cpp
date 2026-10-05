// Finite linker-only probe. Does not instantiate SensorService or read sensors.
#include <dlfcn.h>
#include <cstdio>
#include <cstdlib>
#include <unistd.h>
#include <cstdint>
#include <cstring>
#include "lifecycle_site.h"
int main() {
    setvbuf(stdout,nullptr,_IONBF,0);
    void* p=dlopen("libsensorservice.so",RTLD_NOW|RTLD_GLOBAL);
    if(!p) { printf("PARENT_LOAD_FAILED %s\n",dlerror()); return 2; }
    void* hook=dlsym(p,"_ZN7android14VivoFusionImpl17processRealSensorER15sensors_event_t");
    Dl_info info{};
    if(!hook || !dladdr(hook,&info)) return 3;
    printf("RESOLVED_INTERPOSER=%s\n",info.dli_fname ? info.dli_fname : "unknown");
    void* c=dlopen("libcwb_client.so",RTLD_NOW|RTLD_LOCAL);
    if(!c) { printf("CLIENT_LOAD_FAILED %s\n",dlerror()); return 4; }
    printf("CLIENT_LOADED ctor=%p dtor=%p\n",dlsym(c,"_ZN9CwbClientC1Ev"),dlsym(c,"_ZN9CwbClientD1Ev"));
    printf("LINKER_ONLY no sensor subscription or CWB activation\n");
    // OVSC starts an asynchronous ELF-symbol scanner from its constructor.
    // Immediate process exit previously concealed its invalid table bounds.
    sleep(3);
    printf("ASYNC_INITIALIZATION_SURVIVED\n");
    void* anchor=dlsym(p,"_ZN7android13SensorService22sendRuntimeSensorEventERK15sensors_event_t");
    if(!anchor) return 5;
    const intptr_t offsets[2]={hidl_offset_from_anchor,aidl_offset_from_anchor};
    for(int backend=0;backend<2;++backend) {
        auto* site=static_cast<uint8_t*>(anchor)+offsets[backend];
        uint32_t instruction=0; memcpy(&instruction,site,4);
        if(instruction!=0x58000050u) { printf("LIFECYCLE_NOT_INSTALLED backend=%d\n",backend); return 6; }
        // Null HAL member takes the original -ENODEV branch; no real Binder
        // calls or SensorService instance. Exercise each relocated prologue.
        alignas(16) uint64_t fake[4]{};
        auto activate=reinterpret_cast<int(*)(void*,int,bool)>(site);
        const int result=activate(fake,0x3e9,true);
        printf("LIFECYCLE_EMPTY_HAL backend=%s result=%d\n",backend ? "AIDL" : "HIDL",result);
        if(result!=-19) return 7;
    }
    // Do not explicitly unload a diagnostic's patched parent/trampoline pages.
    // Process exit reclaims every mapping together.
    return 0;
}
