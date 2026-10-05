#pragma once
// Reconstruction of the extracted official SF pixel loop. This is the SF
// branch, NOT the hardware CWB weighted calculation. No capture or worker here.
// Build with -ffp-contract=off; the ARM64 oracle checks integer RGB and matrix.
#include <cmath>
#include <cstdint>
#include <cstddef>
#include "sf_rgb_lut.h"

struct SFMathConfig {
    bool linear_correction;
    float gains[3];
    int thresholds[4]; // tolerance, low split, minimum dark range, high split
};
struct SFMathResult { int rgb[3], purity; };

static inline uint32_t sf_trunc_unsigned(float value) {
    if(!(value>0)) return 0;
    if(double(value)>=4294967295.0) return UINT32_MAX;
    return static_cast<uint32_t>(value);
}
static inline bool sf_rgb_calculate(const uint32_t* pixels, int width, int height,
                                    int stride, float matrix[16],
                                    const SFMathConfig& config, SFMathResult* out) {
    if(!pixels || !matrix || !out || width<=0 || height<=0 || width>512 || height>512 ||
       stride<width || stride>4096) return false;
    for(int i=0;i<16;++i) if(!std::isfinite(matrix[i])) return false;
    for(int i=0;i<3;++i) if(!std::isfinite(config.gains[i])) return false;
    *out={};
    constexpr float epsilon=0x1.a36e2e0000000p-14f; // official single 1e-4
    constexpr double exponent=0.45454543828964233;
    if(config.linear_correction) {
        if(std::fabs(matrix[4])<epsilon) {
            for(int channel=0;channel<3;++channel) {
                if(matrix[channel*5]<0) return false;
                matrix[channel*5]=static_cast<float>(std::pow(double(matrix[channel*5]),exponent));
            }
        } else if(matrix[4]>epsilon && matrix[1]>epsilon) {
            const float luma[3]={0.2125999927520752f,0.7152000069618225f,0.0722000002861023f};
            float gains[3]={1,1,1};
            for(int channel=0;channel<3;++channel)
                if(config.gains[channel]>epsilon && config.gains[channel]<1)
                    gains[channel]=static_cast<float>(std::pow(double(config.gains[channel]),exponent));
            for(int column=0;column<4;++column)
                for(int row=0;row<4;++row)
                    matrix[column*4+row]=column<3 && row<3 ? luma[column]*gains[row] : (column==3 && row==3 ? 1 : 0);
        }
    }
    float sums[3]{};
    uint32_t low_max[3]{},all_max[3]{},high_min[3]={255,255,255},all_min[3]={255,255,255};
    uint32_t count=0;
    for(int y=0;y<height;y+=3) {
        for(int x=0;x<width;x+=3) {
            const uint32_t packed=pixels[size_t(y)*stride+x];
            const float channels[4]={float(packed&255),float((packed>>8)&255),float((packed>>16)&255),float(packed>>24)};
            for(int channel=0;channel<3;++channel) {
                float value=std::fabs(matrix[channel])*channels[0];
                value=value+std::fabs(matrix[4+channel])*channels[1];
                value=value+std::fabs(matrix[8+channel])*channels[2];
                value=value+std::fabs(matrix[12+channel])*channels[3];
                uint32_t corrected=sf_trunc_unsigned(value);
                if(matrix[channel]<epsilon && matrix[4+channel]<epsilon && matrix[8+channel]<epsilon)
                    corrected=255u-corrected;
                if(corrected>all_max[channel]) all_max[channel]=corrected;
                if(corrected<all_min[channel]) all_min[channel]=corrected;
                if(static_cast<int32_t>(corrected)<config.thresholds[1] && corrected>low_max[channel]) low_max[channel]=corrected;
                if(static_cast<int32_t>(corrected)>config.thresholds[3] && corrected<high_min[channel]) high_min[channel]=corrected;
                sums[channel]=sums[channel]+sf_rgb_lut[corrected&255];
            }
            ++count;
        }
    }
    if(!count) return false;
    bool pure=true,black_white=true;
    for(int channel=0;channel<3;++channel) {
        if(low_max[channel]<all_min[channel]) low_max[channel]=all_min[channel];
        if(high_min[channel]>all_max[channel]) high_min[channel]=all_max[channel];
        const auto difference=[](uint32_t a,uint32_t b) -> uint32_t { return a>b ? a-b : b-a; };
        pure=pure && difference(all_max[channel],all_min[channel])<=uint32_t(config.thresholds[0]);
        black_white=black_white && int32_t(high_min[channel])>=config.thresholds[1] &&
            int32_t(all_min[channel])>=config.thresholds[2] && int32_t(low_max[channel])<=config.thresholds[3] &&
            difference(low_max[channel],all_min[channel])<=uint32_t(config.thresholds[0]) &&
            difference(all_max[channel],high_min[channel])<=uint32_t(config.thresholds[0]);
        const uint32_t average=sf_trunc_unsigned((sums[channel]/float(count))*100.0f);
        uint32_t best=100000;
        for(int index=0;index<256;++index) {
            const uint32_t candidate=sf_trunc_unsigned(sf_rgb_lut[index]*100.0f);
            const uint32_t distance=difference(candidate,average);
            if(distance<best) { best=distance; out->rgb[channel]=index; }
        }
    }
    out->purity=pure ? 1 : black_white ? 2 : 0;
    return true;
}
