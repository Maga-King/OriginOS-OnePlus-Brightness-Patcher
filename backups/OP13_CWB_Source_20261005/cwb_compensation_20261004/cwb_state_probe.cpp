// One read-only vendor state snapshot. No ptrace, hook, sensor or display writes.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <linux/dma-buf.h>
#include <sys/syscall.h>
#include <cerrno>

static uintptr_t untag(uintptr_t value) { return value&0x00ffffffffffffffULL; }
static bool read_at(int fd,uintptr_t address,void* out,size_t size) {
    return pread(fd,out,size,static_cast<off_t>(untag(address)))==static_cast<ssize_t>(size);
}
int main(int argc,char** argv) {
    if(argc!=2) return 64;
    const int pid=atoi(argv[1]); if(pid<=1) return 64;
    char path[96]; snprintf(path,sizeof(path),"/proc/%d/maps",pid);
    FILE* maps=fopen(path,"r"); if(!maps) { perror("maps"); return 2; }
    char line[1024]; uintptr_t base=0;
    while(fgets(line,sizeof(line),maps)) {
        unsigned long long low=0,high=0,offset=0; char perms[8]{};
        if(strstr(line,"/vendor/lib64/libcwb_qcom_aidl.so") &&
           sscanf(line,"%llx-%llx %7s %llx",&low,&high,perms,&offset)==4 && offset==0) base=low;
    }
    fclose(maps); if(!base) return 3;
    snprintf(path,sizeof(path),"/proc/%d/mem",pid);
    const int fd=open(path,O_RDONLY|O_CLOEXEC); if(fd<0) { perror("mem"); return 4; }
    uintptr_t proxy=0,service=0,vtable=0;
    if(!read_at(fd,base+0x207c8,&proxy,8) || !proxy ||
       !read_at(fd,proxy+0x10,&service,8) || !service ||
       !read_at(fd,service,&vtable,8) || untag(vtable)!=base+0x1c058) { puts("Unsupported live service ABI"); close(fd); return 5; }
    unsigned char state[0x490]{};
    if(!read_at(fd,service,state,sizeof(state))) { close(fd); return 6; }
    const auto integer=[&](size_t offset) { int32_t value; memcpy(&value,state+offset,4); return value; };
    const auto wide=[&](size_t offset) { int64_t value; memcpy(&value,state+offset,8); return value; };
    timespec now{}; clock_gettime(CLOCK_BOOTTIME,&now);
    const int64_t ns=int64_t(now.tv_sec)*1000000000+now.tv_nsec;
    printf("CWB_STATE power=%d previous=%d postprocess=%u aod_forbidden=%u aod_layer=%u cache_steps=%d cache_valid=%u invalidations=%d rotation=%d buffer_age_ms=%.3f enabled=%u,%u\n",
        integer(0x310),integer(0x30c),state[0x21c],state[0x21e],state[0x32c],integer(0x318),state[0x2f4],integer(0x2f8),integer(0x40c),double(ns-wide(0x378))/1e6,state[0x2c8],state[0x2c9]);
    printf("CWB_ROI enabled=%u requested=%d,%d,%d,%d weights_count=%d\n",state[0x21d],integer(0x26c),integer(0x270),integer(0x274),integer(0x278),integer(0x248));
    // Audited libc++ RGB cache tree: root +0x338, count +0x340;
    // node's Rect +0x1c and tuple RGB +0x2c. Read-only, bounded to 32
    // nodes; a concurrent mutation makes this diagnostic inconclusive.
    const uintptr_t cache_count=static_cast<uintptr_t>(wide(0x340));
    uintptr_t todo[32]{},visited[32]{};
    unsigned pending_nodes=0,seen=0;
    if(cache_count<=32 && wide(0x338)) todo[pending_nodes++]=untag(static_cast<uintptr_t>(wide(0x338)));
    while(pending_nodes && seen<32) {
        const uintptr_t node=todo[--pending_nodes];
        bool repeated=false;
        for(unsigned i=0;i<seen;++i) if(visited[i]==node) repeated=true;
        if(!node || repeated) continue;
        unsigned char contents[56]{};
        if(!read_at(fd,node,contents,sizeof(contents))) break;
        visited[seen++]=node;
        int32_t area[4]{}; uint16_t flags=0;
        memcpy(area,contents+0x1c,sizeof(area)); memcpy(&flags,contents+0x30,sizeof(flags));
        printf("CWB_RGB_CACHE rect=%d,%d,%d,%d RGB=%u,%u,%u flags=%u count=%llu\n",
            area[0],area[1],area[2],area[3],contents[0x2c],contents[0x2d],contents[0x2e],flags,
            static_cast<unsigned long long>(cache_count));
        for(unsigned child=0;child<2;++child) {
            uintptr_t pointer=0; memcpy(&pointer,contents+child*8,8);
            pointer=untag(pointer);
            if(pointer && pending_nodes<32) todo[pending_nodes++]=pointer;
        }
    }
    // Fields independently identified in prepareCwbBuffer's mapper calls.
    // Bounded one-shot reads only. Buffers can change during a snapshot.
    for(unsigned slot=0;slot<2;++slot) {
        const size_t off=slot ? 0x448 : 0x418;
        const uintptr_t pixels=untag(static_cast<uintptr_t>(wide(off)));
        const int64_t allocation=wide(off+0x10),stride=wide(off+0x18);
        const int64_t width=wide(off+0x20),height=wide(off+0x28);
        printf("CWB_BUFFER slot=%u address=%llx format=%d bytes=%lld stride=%lld width=%lld height=%lld\n",
            slot,static_cast<unsigned long long>(pixels),integer(off+8),static_cast<long long>(allocation),static_cast<long long>(stride),static_cast<long long>(width),static_cast<long long>(height));
        if(!pixels || allocation<=0 || allocation>32*1024*1024 || stride<=0 || width<=0 || height<=0 || width>8192 || height>8192 || integer(off+8)!=3) continue;
        if(stride<width || stride>8192 || stride*height*3>allocation) continue;
        int32_t handle[4]{}; int dmafd=-1; void* mapping=MAP_FAILED;
        if(read_at(fd,static_cast<uintptr_t>(wide(slot ? 0x480 : 0x478)),handle,sizeof(handle)) && handle[0]==12 && handle[1]>0 && handle[1]<=8 && handle[3]>=0) {
            snprintf(path,sizeof(path),"/proc/%d/fd/%d",pid,handle[3]);
            dmafd=open(path,O_RDONLY|O_CLOEXEC);
            if(dmafd<0) {
                const int open_error=errno;
                const int pidfd=static_cast<int>(syscall(__NR_pidfd_open,pid,0));
                if(pidfd>=0) { dmafd=static_cast<int>(syscall(__NR_pidfd_getfd,pidfd,handle[3],0)); close(pidfd); }
                printf("CWB_DMA_DUP open_errno=%d duplicate=%d errno=%d\n",open_error,dmafd,errno);
            }
            if(dmafd>=0) mapping=mmap(nullptr,static_cast<size_t>(allocation),PROT_READ,MAP_SHARED,dmafd,0);
            printf("CWB_DMA slot=%u original_fd=%d open=%d mapped=%d\n",slot,handle[3],dmafd>=0,mapping!=MAP_FAILED);
        }
        dma_buf_sync sync{DMA_BUF_SYNC_START|DMA_BUF_SYNC_READ};
        const bool synced=mapping!=MAP_FAILED && ioctl(dmafd,DMA_BUF_IOCTL_SYNC,&sync)==0;
        auto* row=static_cast<unsigned char*>(malloc(static_cast<size_t>(stride*3)));
        if(!row) { if(synced) { sync.flags=DMA_BUF_SYNC_END|DMA_BUF_SYNC_READ; ioctl(dmafd,DMA_BUF_IOCTL_SYNC,&sync); } if(mapping!=MAP_FAILED) munmap(mapping,static_cast<size_t>(allocation)); if(dmafd>=0) close(dmafd); continue; }
        uint64_t nonzero=0,sum[3]{}; int minx=int(width),miny=int(height),maxx=-1,maxy=-1; bool ok=true;
        for(int y=0;y<height;++y) {
            if(mapping!=MAP_FAILED) memcpy(row,static_cast<unsigned char*>(mapping)+y*stride*3,static_cast<size_t>(stride*3));
            else if(!read_at(fd,pixels+uintptr_t(y*stride*3),row,static_cast<size_t>(stride*3))) { ok=false; break; }
            for(int x=0;x<width;++x) {
                const auto* rgb=row+3*x;
                if(rgb[0] || rgb[1] || rgb[2]) {
                    ++nonzero; if(x<minx) minx=x; if(x>maxx) maxx=x; if(y<miny) miny=y; if(y>maxy) maxy=y;
                }
                for(unsigned ch=0;ch<3;++ch) sum[ch]+=rgb[ch];
            }
        }
        printf("CWB_PIXELS slot=%u complete=%d nonzero=%llu bounds=%d,%d-%d,%d sums=%llu,%llu,%llu\n",slot,ok,
            static_cast<unsigned long long>(nonzero),minx,miny,maxx,maxy,
            static_cast<unsigned long long>(sum[0]),static_cast<unsigned long long>(sum[1]),static_cast<unsigned long long>(sum[2]));
        free(row);
        if(synced) { sync.flags=DMA_BUF_SYNC_END|DMA_BUF_SYNC_READ; ioctl(dmafd,DMA_BUF_IOCTL_SYNC,&sync); }
        if(mapping!=MAP_FAILED) munmap(mapping,static_cast<size_t>(allocation));
        if(dmafd>=0) close(dmafd);
    }
    const uintptr_t configs=untag(static_cast<uintptr_t>(wide(0x1e0)));
    const uintptr_t end=untag(static_cast<uintptr_t>(wide(0x1e8)));
    const int id=integer(0x214);
    if(configs && end>=configs && end-configs<=28*256 && id>=0 && (uintptr_t(id)+1)*28<=end-configs) {
        int32_t values[7]{};
        if(read_at(fd,configs+uintptr_t(id)*28,values,sizeof(values))) {
            printf("ACTIVE_CONFIG index=%d values=%d,%d,%d,%d,%d,%d,%d\n",id,values[0],values[1],values[2],values[3],values[4],values[5],values[6]);
        }
    }
    close(fd); return 0;
}
