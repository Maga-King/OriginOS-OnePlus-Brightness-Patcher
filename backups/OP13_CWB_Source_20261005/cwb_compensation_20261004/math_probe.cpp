#include <cstdio>
#include <cstdlib>
#include "factory_calibration.h"
#include "compensation_math.h"
int main(int argc,char** argv) {
    if(argc!=10) { fprintf(stderr,"DBV R G B rawR rawG rawB rawC loading\n"); return 64; }
    long double device[9][4]{};
    if(!read_factory_calibration(device)) { fprintf(stderr,"FACTORY_CALIBRATION_UNAVAILABLE\n"); return 2; }
    int rgb[3]; float raw[4];
    for(int i=0;i<3;++i) rgb[i]=atoi(argv[i+2]);
    for(int i=0;i<4;++i) raw[i]=strtof(argv[i+5],nullptr);
    CompensationResult result{};
    if(!compensation_calculate(atoi(argv[1]),rgb,raw,static_cast<uint32_t>(strtoul(argv[9],nullptr,10)),device,&result)) return 3;
    printf("FACTORY_CALIBRATION=runtime LEVEL=%d IR=%.12Lf IR_LEVEL=%d COUNT_LEVEL=%d LUX=%.12f\n",result.level,result.ir,result.ir_level,result.count_level,result.lux);
    for(int i=0;i<4;++i) printf("%c CAL=%.0Lf LEAK=%.12Lf CORRECTED=%.12Lf\n","RGBC"[i],device[result.level][i],result.leak[i],result.corrected[i]);
    return 0;
}
