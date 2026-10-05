#pragma once
#include <android/binder_ibinder.h>
#include <dlfcn.h>
#include <android/binder_parcel.h>
#include <android/binder_status.h>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <cmath>

static void* cal_create(void* p) { return p; }
static void cal_destroy(void*) {}
static binder_status_t cal_transaction(AIBinder*,transaction_code_t,const AParcel*,AParcel*) {
    return STATUS_UNKNOWN_TRANSACTION;
}
static bool cal_string_alloc(void* p,int32_t length,char** buffer) {
    if(length<=0 || length>262144) return false;
    *buffer=static_cast<char*>(malloc(static_cast<size_t>(length)));
    *static_cast<char**>(p)=*buffer;
    return *buffer!=nullptr;
}
static AIBinder* get_sensor_feature() {
    // Service-manager entry is a platform API, not in the NDK stub library.
    auto check=reinterpret_cast<AIBinder*(*)(const char*)>(dlsym(RTLD_DEFAULT,"AServiceManager_checkService"));
    if(!check) return nullptr;
    AIBinder* binder=check("vendor.oplus.hardware.oplusSensor.ISensorFeature/default");
    if(!binder) return nullptr;
    static AIBinder_Class* cls=AIBinder_Class_define("vendor.oplus.hardware.oplusSensor.ISensorFeature",cal_create,cal_destroy,cal_transaction);
    if(!cls || !AIBinder_associateClass(binder,cls)) { AIBinder_decStrong(binder); return nullptr; }
    return binder;
}
static inline int write_screenshot_info(AIBinder* binder,int64_t start,int64_t end,unsigned int sequence) {
    if(!binder || start<=0 || end<=start || sequence==0 || sequence>65534) return INT32_MIN;
    // Exact official callback format: start,end,sequence,0 (0 denotes CWB, 1 SF).
    char payload[100];
    const int n=snprintf(payload,sizeof(payload),"%lld,%lld,%u,0",static_cast<long long>(start),static_cast<long long>(end),sequence);
    if(n<=0 || n>=static_cast<int>(sizeof(payload))) return INT32_MIN;
    AParcel *in=nullptr,*out=nullptr;
    AStatus* status=nullptr;
    int32_t result=INT32_MIN;
    if(AIBinder_prepareTransaction(binder,&in)==STATUS_OK &&
       AParcel_writeString(in,"ssc_screenshot_info",19)==STATUS_OK &&
       AParcel_writeString(in,payload,n)==STATUS_OK &&
       AIBinder_transact(binder,8,&in,&out,0x10000000)==STATUS_OK && out &&
       AParcel_readStatusHeader(out,&status)==STATUS_OK && status && AStatus_isOk(status)) {
        if(AParcel_readInt32(out,&result)!=STATUS_OK) result=INT32_MIN;
    }
    if(status) AStatus_delete(status);
    if(in) AParcel_delete(in);
    if(out) AParcel_delete(out);
    return result;
}
static bool read_factory_calibration(long double result[9][4]) {
    // Audited transaction 2; never write calibration or use another device's W_VIEW.
    AIBinder* binder=get_sensor_feature();
    if(!binder) return false;
    AParcel *in=nullptr,*out=nullptr;
    char* json=nullptr;
    AStatus* status=nullptr;
    bool ok=false;
    if(AIBinder_prepareTransaction(binder,&in)==STATUS_OK) {
        if(AParcel_writeInt32(in,33171070)==STATUS_OK) {
            const auto tx=AIBinder_transact(binder,2,&in,&out,0);
            if(tx==STATUS_OK && out && AParcel_readStatusHeader(out,&status)==STATUS_OK &&
               status && AStatus_isOk(status) && AParcel_readString(out,&json,cal_string_alloc)==STATUS_OK) ok=true;
        }
    }
    if(status) AStatus_delete(status);
    if(in) AParcel_delete(in);
    if(out) AParcel_delete(out);
    AIBinder_decStrong(binder);
    if(ok && json) {
        for(int lv=0;lv<9 && ok;++lv) for(int ch=0;ch<4;++ch) {
            char key[32];
            snprintf(key,sizeof(key),"\"W_VIEW_%c_%d\"","RGBC"[ch],lv);
            const char* s=strstr(json,key);
            if(!s || !(s=strchr(s,':'))) { ok=false; break; }
            ++s;
            while(*s==' ' || *s=='\t' || *s=='\r' || *s=='\n' || *s=='\"') ++s;
            char* end=nullptr;
            const long double value=strtold(s,&end);
            if(end==s || !std::isfinite(value) || !(value>0) || value>100000000) { ok=false; break; }
            result[lv][ch]=value;
        }
    }
    free(json);
    return ok;
}
