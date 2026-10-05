#pragma once
#include <cmath>
#include <cstdint>
#include "official_profile.h"

struct CompensationResult {
    long double leak[4], corrected[4], ir;
    double lux;
    int level, ir_level, count_level;
};

static long double dot(const long double* a, const long double* b, int n) {
    long double s=0;
    for (int i=0; i<n; ++i) s += a[i]*b[i];
    return s;
}
static long double linearity(int ch, int level, int dbv) {
    const auto* p=linearity_parameters[ch][level];
    const long double x=dbv;
    switch(linearity_type[ch][level]) {
        case 1: return p[0]*powl(x,p[1]);
        case 2: return p[0]*expl(p[1]*x);
        case 3: return p[0]*x*x*x+p[1]*x*x+p[2]*x+p[3];
        default: return NAN;
    }
}
static bool compensation_calculate(int dbv, const int rgb[3], const float raw[4],
                                    uint32_t loading, const long double device[9][4],
                                    CompensationResult* out) {
    if (!out || dbv<0 || dbv>4094) return false;
    for(int ch=0;ch<4;++ch) if (!std::isfinite(raw[ch]) || raw[ch]<0) return false;
    for(int i=0;i<3;++i) if(rgb[i]<0 || rgb[i]>255) return false;
    *out={};
    int level=0;
    while(level<8 && dbv>brightness_max[level]) ++level;
    out->level=level;
    const long double r=rgb[0], g=rgb[1], b=rgb[2];
    const long double rt[20]={1,r,g,b,r*r,r*g,r*b,g*g,g*b,b*b,
        r*r*r,r*r*g,r*r*b,r*g*g,r*g*b,r*b*b,g*g*g,g*g*b,g*b*b,b*b*b};
    const long double scale=loading>100000000u ? static_cast<long double>(loading)/100000000 : 1;
    for(int ch=0;ch<4;++ch) {
        long double leak=0;
        if(dbv>0) {
            if(!(device[level][ch]>0) || !(golden[level][ch]>0)) return false;
            const long double x=linearity(ch,level,dbv);
            const long double lt[35]={1,x,r,g,b,x*x,x*r,x*g,x*b,r*r,r*g,r*b,g*g,g*b,b*b,
                x*x*x,x*x*r,x*x*g,x*x*b,x*r*r,x*r*g,x*r*b,x*g*g,x*g*b,x*b*b,
                r*r*r,r*r*g,r*r*b,r*g*g,r*g*b,r*b*b,g*g*g,g*g*b,g*b*b,b*b*b};
            leak=dot(leak_parameters[ch][level],lt,35)*dot(colour_parameters[ch][level],rt,20)*device[level][ch]/golden[level][ch];
            if(!std::isfinite(leak)) return false;
            leak=fmaxl(0,leak)*scale;
        }
        out->leak[ch]=leak;
        out->corrected[ch]=fmaxl(0,static_cast<long double>(raw[ch])-leak);
    }
    const auto* v=out->corrected;
    // Official default IRRatioFormulaType=0, SM8750 SensorModuleId=3.
    // calculate_ir_ratio uses binary128 and clamps negative values to zero.
    out->ir=v[3]>=0.0000001L ? fmaxl(0,((v[0]+v[1]+v[2]-v[3])/v[3])*0.5L) : 0;
    out->ir_level=out->ir<ir_threshold[0] ? 0 : out->ir<ir_threshold[1] ? 1 : 2;
    int ir_level=0;
    while(ir_level<2 && dbv>ir_brightness_max[ir_level]) ++ir_level;
    bool low_count=true;
    for(int ch=0;ch<4;++ch) if(count_max[ch]>=0 && v[ch]>=count_max[ch]) low_count=false;
    out->count_level=low_count ? 0 : -1;
    const long double* coeff;
    if(dbv==0) coeff=off_coeff[out->ir_level][v[3]>=2400 ? 1 : 0];
    else if(low_count) coeff=count_coeff[out->ir_level][0];
    else coeff=lux_coeff[out->ir_level][ir_level];
    // Native calculates each product in binary128, then accumulates in double.
    double lux=0;
    for(int ch=0;ch<4;++ch) lux+=static_cast<double>(coeff[ch]*v[ch]);
    if(!std::isfinite(lux)) return false;
    out->lux=lux>=1 ? lux : 0; // official LowLightAccuracy=1
    return true;
}
