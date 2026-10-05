// One read-only snapshot of the currently built system-server helper status.
// The offset comes from this exact helper's symbol table; no remote calls/hooks.
#include "cwb_compensator.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <fcntl.h>
#include <unistd.h>
#include <elf.h>
static uint64_t locate_status(const char* path) {
    FILE* file=fopen(path,"rb"); if(!file) return 0;
    Elf64_Ehdr header{}; uint64_t result=0;
    if(fread(&header,1,sizeof(header),file)!=sizeof(header) ||
       memcmp(header.e_ident,ELFMAG,SELFMAG) || header.e_ident[EI_CLASS]!=ELFCLASS64 ||
       header.e_ident[EI_DATA]!=ELFDATA2LSB || header.e_machine!=EM_AARCH64 ||
       header.e_shentsize!=sizeof(Elf64_Shdr) || header.e_shnum>4096) { fclose(file); return 0; }
    for(unsigned i=0;i<header.e_shnum && !result;++i) {
        Elf64_Shdr symbols{},strings{};
        if(fseeko(file,header.e_shoff+i*sizeof(symbols),SEEK_SET) ||
           fread(&symbols,1,sizeof(symbols),file)!=sizeof(symbols)) break;
        if(symbols.sh_type!=SHT_SYMTAB || symbols.sh_entsize!=sizeof(Elf64_Sym) ||
           symbols.sh_size>4*1024*1024 || symbols.sh_link>=header.e_shnum) continue;
        if(fseeko(file,header.e_shoff+symbols.sh_link*sizeof(strings),SEEK_SET) ||
           fread(&strings,1,sizeof(strings),file)!=sizeof(strings) || strings.sh_size>4*1024*1024) break;
        for(uint64_t j=0;j<symbols.sh_size/sizeof(Elf64_Sym);++j) {
            Elf64_Sym symbol{}; char name[sizeof("_ZL6status")]{};
            if(fseeko(file,symbols.sh_offset+j*sizeof(symbol),SEEK_SET) ||
               fread(&symbol,1,sizeof(symbol),file)!=sizeof(symbol)) break;
            if(symbol.st_size!=sizeof(cos_comp_status) || symbol.st_name+sizeof(name)>strings.sh_size) continue;
            if(fseeko(file,strings.sh_offset+symbol.st_name,SEEK_SET) || fread(name,1,sizeof(name),file)!=sizeof(name)) break;
            if(!memcmp(name,"_ZL6status",sizeof(name))) { result=symbol.st_value; break; }
        }
    }
    fclose(file); return result;
}
int main(int argc,char** argv) {
    if(argc!=2 && argc!=3) return 64;
    const int pid=atoi(argv[1]);
    char path[80],line[1024];
    snprintf(path,sizeof(path),"/proc/%d/root/system/lib64/nc.so",pid);
    const auto offset=argc==3 ? strtoull(argv[2],nullptr,0) : locate_status(path);
    if(pid<=1 || !offset || offset>1024*1024) { puts("STATUS_UNAVAILABLE: unsupported/missing helper symbol layout"); return 64; }
    snprintf(path,sizeof(path),"/proc/%d/maps",pid);
    FILE* maps=fopen(path,"r"); if(!maps) return 2;
    unsigned long long base=0;
    while(fgets(line,sizeof(line),maps)) {
        unsigned long long low=0,high=0,file_offset=0; char perms[8]{};
        if(strstr(line,"/system/lib64/nc.so") &&
           sscanf(line,"%llx-%llx %7s %llx",&low,&high,perms,&file_offset)==4 && file_offset==0)
            base=low;
    }
    fclose(maps); if(!base) { puts("STATUS_UNAVAILABLE: helper is not loaded in system_server"); return 3; }
    snprintf(path,sizeof(path),"/proc/%d/mem",pid);
    const int fd=open(path,O_RDONLY|O_CLOEXEC); if(fd<0) return 4;
    cos_comp_status status{};
    const auto bytes=pread(fd,&status,sizeof(status),static_cast<off_t>(base+offset));
    close(fd); if(bytes!=sizeof(status)) return 5;
    if(status.ready<0 || status.ready>1 || status.active<0 || status.active>1 ||
       status.rgb[0]<0 || status.rgb[0]>255 || status.rgb[1]<0 || status.rgb[1]>255 ||
       status.rgb[2]<0 || status.rgb[2]>255) { puts("STATUS_UNAVAILABLE: inconsistent live snapshot"); return 6; }
    printf("COMP_SNAPSHOT ready=%d active=%d RGB=%d,%d,%d DBV=%d raw=%.6f lux=%.6f callbacks=%llu calculated=%llu missing=%llu timing=%llu/%llu held=%llu rejected=%llu ratio=%.6f sequence=%u\n",
        status.ready,status.active,status.rgb[0],status.rgb[1],status.rgb[2],status.dbv,status.raw_lux,status.lux,
        static_cast<unsigned long long>(status.callbacks),static_cast<unsigned long long>(status.processed),
        static_cast<unsigned long long>(status.missing_sample),static_cast<unsigned long long>(status.timing_sent),
        static_cast<unsigned long long>(status.timing_failed),static_cast<unsigned long long>(status.held),
        static_cast<unsigned long long>(status.rejected_window),status.match_ratio,status.matched_sequence);
    puts("READ_ONLY snapshot may race live updates; no subscriptions or SSC writes");
    return 0;
}
