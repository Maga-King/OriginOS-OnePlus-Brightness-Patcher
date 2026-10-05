// Linker-only check: never instantiate the service or allocate CWB buffers.
#include <dlfcn.h>
#include <cstdio>
int main(int argc,char** argv) {
    if(argc!=2) return 1;
    void* library=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
    if(!library) { printf("LOAD_FAILED %s\n",dlerror()); return 2; }
    auto symbol=dlsym(library,"_ZN4aidl6vendor5oplus8hardware3cwb14implementation10CwbService16prepareCwbBufferEv");
    if(!symbol) { printf("SYMBOL_FAILED %s\n",dlerror()); return 3; }
    printf("VENDOR_LOADED prepareCwbBuffer=%p; no service creation or capture\n",symbol);
    dlclose(library);
    return 0;
}
