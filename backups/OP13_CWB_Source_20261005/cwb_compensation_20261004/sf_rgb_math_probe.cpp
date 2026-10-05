// Offline batch mathematical comparison; stdin/stdout, no Android APIs.
#include "sf_rgb_math.h"
#include <cstdio>
#include <vector>
int main() {
    int width=0,height=0,linear=0;
    while(std::scanf("%d %d %d",&width,&height,&linear)==3) {
        if(width<=0 || height<=0 || width>64 || height>64) return 64;
        SFMathConfig config{}; config.linear_correction=linear!=0;
        for(auto& threshold:config.thresholds) if(std::scanf("%d",&threshold)!=1) return 64;
        for(auto& gain:config.gains) if(std::scanf("%f",&gain)!=1) return 64;
        float matrix[16]; for(auto& v:matrix) if(std::scanf("%f",&v)!=1) return 64;
        std::vector<uint32_t> pixels(size_t(width)*height);
        for(auto& pixel:pixels) {
            unsigned r,g,b,a;
            if(std::scanf("%u %u %u %u",&r,&g,&b,&a)!=4 || r>255 || g>255 || b>255 || a>255) return 64;
            pixel=r|(g<<8)|(b<<16)|(a<<24);
        }
        SFMathResult result{};
        bool ok=sf_rgb_calculate(pixels.data(),width,height,width,matrix,config,&result);
        std::printf("%d %d %d %d %d",ok,result.rgb[0],result.rgb[1],result.rgb[2],result.purity);
        for(float v:matrix) std::printf(" %.9g",double(v));
        std::puts("");
    }
}
