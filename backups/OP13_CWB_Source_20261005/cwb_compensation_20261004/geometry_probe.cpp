// Finite official-client geometry diagnostic. No sensors, SSC writes or screenshots.
#include <dlfcn.h>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <unistd.h>
struct Rect { int32_t left,top,right,bottom; };
struct FloatRect { float left,top,right,bottom; };
struct Vec { int32_t *begin,*end,*capacity; };
struct Record { uint32_t word[10]; };
static void callback(const Record& r) {
    printf("CAPTURE");
    for(unsigned i=0;i<10;++i) printf(" %u",r.word[i]);
    printf("\n");
}
int main(int argc,char** argv) {
    const bool normalized=argc==2 && strcmp(argv[1],"--normalized")==0;
    const bool native_sample=argc==2 && strcmp(argv[1],"--native-sample")==0;
    const bool native_only=native_sample || (argc==2 && strcmp(argv[1],"--native")==0);
    const bool sample=normalized || native_sample || (argc==2 && strcmp(argv[1],"--sample")==0);
    setvbuf(stdout,nullptr,_IONBF,0);
    void* lib=dlopen("libcwb_client.so",RTLD_NOW|RTLD_LOCAL);
    if(!lib) { printf("LOAD_FAILED %s\n",dlerror()); return 2; }
    auto ctor=reinterpret_cast<void(*)(void*)>(dlsym(lib,"_ZN9CwbClientC1Ev"));
    auto dtor=reinterpret_cast<void(*)(void*)>(dlsym(lib,"_ZN9CwbClientD1Ev"));
    auto resolution=reinterpret_cast<bool(*)(void*,Rect,Vec&)>(dlsym(lib,"_ZN9CwbClient19getScreenResolutionEN7android4RectERNSt3__16vectorIiNS2_9allocatorIiEEEE"));
    auto activate=reinterpret_cast<int(*)(void*,Rect,bool)>(dlsym(lib,"_ZN9CwbClient18activateScreenShotEN7android4RectEb"));
    auto activate_float=reinterpret_cast<int(*)(void*,FloatRect,bool)>(dlsym(lib,"_ZN9CwbClient18activateScreenShotEN7android9FloatRectEb"));
    auto setcb=reinterpret_cast<void(*)(void*,void(*)(const Record&))>(dlsym(lib,"_ZN9CwbClient24setCWBScreenShotCallbackEPFvR9Rgb_valusE"));
    auto display=reinterpret_cast<void(*)(void*,unsigned)>(dlsym(lib,"_ZN9CwbClient17setCWBDisplayTypeEj"));
    if(!ctor || !dtor || !resolution || !activate || !setcb || !display || (normalized && !activate_float)) return 3;
    // Official loadCommonConfig divides each edge by its reference dimension.
    // FloatRect's official wrapper then truncates edge*100000 and adds bit31.
    const FloatRect fractions{1010.f/1440.f,148.f/3168.f,1048.f/1440.f,190.f/3168.f};
    const auto encode=[](float v) { return static_cast<int32_t>(static_cast<uint32_t>(v*100000.f)|0x80000000u); };
    const Rect encoded{encode(fractions.left),encode(fractions.top),encode(fractions.right),encode(fractions.bottom)};
    const Rect rects[2]={{1010,148,1048,190},{757,111,786,143}};
    for(const auto& rect:rects) {
        if((normalized || native_only) && &rect!=&rects[0]) break;
        const Rect query=normalized ? encoded : rect;
        void* client=calloc(1,0x400); if(!client) return 4;
        ctor(client); display(client,0);
        Vec dims{};
        const bool rc=resolution(client,query,dims);
        printf("RECT %d %d %d %d NORMALIZED=%d RESOLUTION=%d DATA",query.left,query.top,query.right,query.bottom,normalized,rc);
        if(dims.begin && dims.end>=dims.begin && dims.end-dims.begin<32)
            for(auto* p=dims.begin;p!=dims.end;++p) printf(" %d",*p);
        printf("\n"); free(dims.begin);
        if(sample) {
            *reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(client)+0x124)=250;
            setcb(client,callback);
            printf("START=%d\n",normalized ? activate_float(client,fractions,true) : activate(client,rect,true));
            sleep(3);
            printf("STOP=%d\n",normalized ? activate_float(client,fractions,false) : activate(client,rect,false));
            usleep(400000);
            setcb(client,nullptr);
        }
        dtor(client); free(client);
    }
    dlclose(lib);
    printf("DONE no sensor subscription or SSC writes\n");
}
