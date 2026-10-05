// Finite read-only ROI capture through the CURRENT Vivo AIDL service.
// Does not register sensor services, construct CWB, write SSC, change settings,
// or patch SF/system_server. Diagnostic mean RGB is NOT official weighted RGB.
#include <android/binder_ibinder.h>
#include <android/binder_parcel.h>
#include <android/hardware_buffer.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <initializer_list>
#include <pthread.h>
#include <time.h>
#include "sf_rgb_math.h"

using ReadResult = int (*)(void*, const void*);
using DestroyResult = void (*)(void*);
using ViewParcel = const void* (*)(const AParcel*);
using ToBuffer = AHardwareBuffer* (*)(void*);
using WaitFence = int (*)(void*, int);
static ReadResult read_result;
static DestroyResult destroy_result;
static ViewParcel view_parcel;
static ToBuffer to_buffer;
static WaitFence wait_fence;
static void* result_vtable;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static bool completed;
static int result_code = -10000;

static void* create(void* value) { return value; }
static void destroy(void*) {}
static binder_status_t unknown(AIBinder*, transaction_code_t, const AParcel*, AParcel*) {
    return STATUS_UNKNOWN_TRANSACTION;
}
static binder_status_t receive(AIBinder*, transaction_code_t code, const AParcel* parcel, AParcel*) {
    if (code != 1) return STATUS_UNKNOWN_TRANSACTION;
    int32_t present = 0;
    if (AParcel_readInt32(parcel, &present) != STATUS_OK || present != 1) return STATUS_BAD_VALUE;
    alignas(16) unsigned char result[256]{};
    memcpy(result, &result_vtable, sizeof(result_vtable));
    int rc = read_result(result, view_parcel(parcel));
    void* graphic = nullptr;
    memcpy(&graphic, result + 8, sizeof(graphic));
    void* fence = nullptr;
    memcpy(&fence, result + 0x10, sizeof(fence));
    int32_t fence_tag = -1;
    memcpy(&fence_tag, result + 0x18, 4);
    printf("CALLBACK read=%d buffer=%p fence_tag=%d secure=%u hdr=%u\n",
           rc, graphic, fence_tag, result[0x20], result[0x21]);
    if (rc == 0 && fence_tag == 0 && fence) rc = wait_fence(fence, 1000);
    if (rc == 0 && graphic && !result[0x20]) {
        AHardwareBuffer* hardware = to_buffer(graphic);
        AHardwareBuffer_Desc desc{};
        AHardwareBuffer_describe(hardware, &desc);
        printf("ROI_BUFFER width=%u height=%u stride=%u format=%u usage=%llu\n",
               desc.width, desc.height, desc.stride, desc.format,
               static_cast<unsigned long long>(desc.usage));
        if (!desc.width || !desc.height || desc.width > 512 || desc.height > 512 ||
            desc.stride < desc.width || desc.stride > 4096 || desc.format != 1) {
            rc = -10001; // Refuse accidental full-frame or non-RGBA capture.
        } else {
            void* pixels = nullptr;
            rc = AHardwareBuffer_lock(hardware, AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN, -1, nullptr, &pixels);
            if (rc == 0 && pixels) {
                uint64_t total[3]{}, count = uint64_t(desc.width) * desc.height;
                for (unsigned y = 0; y < desc.height; ++y) {
                    const auto* row = static_cast<const unsigned char*>(pixels) + uint64_t(y) * desc.stride * 4;
                    for (unsigned x = 0; x < desc.width; ++x)
                        for (unsigned channel = 0; channel < 3; ++channel) total[channel] += row[x * 4 + channel];
                }
                printf("ROI_MEAN_DIAGNOSTIC RGB=%.3f,%.3f,%.3f pixels=%llu NOT_OFFICIAL_WEIGHTED_RGB\n",
                       double(total[0]) / count, double(total[1]) / count, double(total[2]) / count,
                       static_cast<unsigned long long>(count));
                // Verify reconstructed official SF math on this real tiny ROI.
                // Identity is explicitly a diagnostic input, NOT a substitute
                // for acquiring the actual runtime display color matrix.
                float matrix[16]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
                const SFMathConfig configuration{false,{1,1,1},{2,216,32,38}};
                SFMathResult color{};
                if(sf_rgb_calculate(static_cast<const uint32_t*>(pixels),int(desc.width),int(desc.height),int(desc.stride),matrix,configuration,&color))
                    printf("SF_ALGORITHM_IDENTITY RGB=%d,%d,%d purity=%d MATRIX=IDENTITY NOT_RUNTIME_DISPLAY_MATRIX\n",
                           color.rgb[0],color.rgb[1],color.rgb[2],color.purity);
                AHardwareBuffer_unlock(hardware, nullptr);
            }
        }
    } else if (rc == 0) rc = -10002;
    destroy_result(result);
    pthread_mutex_lock(&mutex);
    result_code = rc;
    completed = true;
    pthread_cond_signal(&changed);
    pthread_mutex_unlock(&mutex);
    return STATUS_OK;
}

static bool write_capture(AParcel* in, int left, int top, int right, int bottom) {
    // Match actual BpSurfaceComposer::captureDisplayById: non-null CaptureArgs
    // followed by a size-delimited AIDL parcelable. Unknown Vivo extensions
    // retain the receiver's native constructor defaults, not guessed bytes.
    if (AParcel_writeInt32(in, 1) != STATUS_OK) return false;
    const int32_t start = AParcel_getDataPosition(in);
    if (AParcel_writeInt32(in, 0) != STATUS_OK || AParcel_writeInt32(in, 1) != STATUS_OK ||
        AParcel_writeInt32(in, 1) != STATUS_OK) return false;
    // ARect: size field plus four coordinates, with nullable presence above.
    for (int value : {20, left, top, right, bottom})
        if (AParcel_writeInt32(in, value) != STATUS_OK) return false;
    if (AParcel_writeFloat(in, 1.0f) != STATUS_OK || AParcel_writeFloat(in, 1.0f) != STATUS_OK)
        return false;
    // captureSecure=false, uid=-1, V0_SRGB, allowProtected=false,
    // grayscale=false, empty excluded handles, seamless display-space hint.
    for (int value : {0, -1, 0x8810000, 0, 0, 0, 1})
        if (AParcel_writeInt32(in, value) != STATUS_OK) return false;
    const int32_t end = AParcel_getDataPosition(in);
    if (AParcel_setDataPosition(in, start) != STATUS_OK ||
        AParcel_writeInt32(in, end - start) != STATUS_OK ||
        AParcel_setDataPosition(in, end) != STATUS_OK) return false;
    return true;
}

struct VectorResult { uint64_t* begin; uint64_t* end; uint64_t* capacity; ~VectorResult() {} };
using GetDisplays = VectorResult (*)();
struct NativeStrong { void* pointer; ~NativeStrong() {} };
using GetToken = NativeStrong (*)(uint64_t);
using FromPlatformBinder = AIBinder* (*)(const NativeStrong&);

int main(int argc, char** argv) {
    if (argc != 5) { puts("Usage: sf_roi_probe left top right bottom (one bounded capture)"); return 64; }
    int values[4];
    for (unsigned i = 0; i < 4; ++i) {
        char* end = nullptr;
        long value = strtol(argv[i + 1], &end, 10);
        if (!end || *end || value < 0 || value > 8192) return 64;
        values[i] = int(value);
    }
    if (values[2] <= values[0] || values[3] <= values[1] ||
        values[2] - values[0] > 512 || values[3] - values[1] > 512) return 64;
    void* gui = dlopen("libgui.so", RTLD_NOW | RTLD_LOCAL);
    void* ui = dlopen("libui.so", RTLD_NOW | RTLD_LOCAL);
    void* binder = dlopen("libbinder_ndk.so", RTLD_NOW | RTLD_LOCAL);
    if (!gui || !ui || !binder) { printf("Load failed: %s\n", dlerror()); return 2; }
    read_result = reinterpret_cast<ReadResult>(dlsym(gui, "_ZN7android3gui20ScreenCaptureResults14readFromParcelEPKNS_6ParcelE"));
    destroy_result = reinterpret_cast<DestroyResult>(dlsym(gui, "_ZN7android3gui20ScreenCaptureResultsD2Ev"));
    view_parcel = reinterpret_cast<ViewParcel>(dlsym(binder, "_Z26AParcel_viewPlatformParcelPK7AParcel"));
    to_buffer = reinterpret_cast<ToBuffer>(dlsym(ui, "_ZN7android13GraphicBuffer17toAHardwareBufferEv"));
    wait_fence = reinterpret_cast<WaitFence>(dlsym(ui, "_ZN7android5Fence4waitEi"));
    auto* table = static_cast<unsigned char*>(dlsym(gui, "_ZTVN7android3gui20ScreenCaptureResultsE"));
    result_vtable = table ? table + 16 : nullptr;
    // The destructor is hidden on this ROM. Use the exported class vtable's
    // standard non-deleting virtual destructor, not a guessed code offset.
    if (!destroy_result && result_vtable) memcpy(&destroy_result, result_vtable, sizeof(destroy_result));
    auto get_displays = reinterpret_cast<GetDisplays>(dlsym(gui, "_ZN7android21SurfaceComposerClient21getPhysicalDisplayIdsEv"));
    auto get_token = reinterpret_cast<GetToken>(dlsym(gui, "_ZN7android21SurfaceComposerClient23getPhysicalDisplayTokenENS_17PhysicalDisplayIdE"));
    auto from_platform = reinterpret_cast<FromPlatformBinder>(dlsym(binder, "_Z27AIBinder_fromPlatformBinderRKN7android2spINS_7IBinderEEE"));
    auto check_service = reinterpret_cast<AIBinder* (*)(const char*)>(dlsym(binder, "AServiceManager_checkService"));
    auto set_threads = reinterpret_cast<bool (*)(uint32_t)>(dlsym(binder, "ABinderProcess_setThreadPoolMaxThreadCount"));
    auto start_threads = reinterpret_cast<void (*)()>(dlsym(binder, "ABinderProcess_startThreadPool"));
    if (!read_result || !destroy_result || !view_parcel || !to_buffer || !wait_fence ||
        !result_vtable || !get_displays || !get_token || !from_platform || !check_service || !set_threads || !start_threads) {
        printf("Unsupported live ABI: read=%p dtor=%p parcel=%p buffer=%p fence=%p vtable=%p displays=%p service=%p setThreads=%p startThreads=%p\n",
               reinterpret_cast<void*>(read_result), reinterpret_cast<void*>(destroy_result),
               reinterpret_cast<void*>(view_parcel), reinterpret_cast<void*>(to_buffer), reinterpret_cast<void*>(wait_fence),
               result_vtable, reinterpret_cast<void*>(get_displays), reinterpret_cast<void*>(check_service),
               reinterpret_cast<void*>(set_threads), reinterpret_cast<void*>(start_threads));
        return 3;
    }
    const auto displays = get_displays();
    if (!displays.begin || displays.end <= displays.begin || displays.end - displays.begin > 4) return 4;
    const uint64_t display_id = displays.begin[0];
    const auto token = get_token(display_id);
    AIBinder* display_token = token.pointer ? from_platform(token) : nullptr;
    if (!display_token) return 4;
    printf("DISPLAY_ID=%llu crop=%d,%d-%d,%d\n", static_cast<unsigned long long>(display_id),
           values[0], values[1], values[2], values[3]);
    AIBinder* service = check_service("SurfaceFlingerAIDL");
    auto* service_class = AIBinder_Class_define("android.gui.ISurfaceComposer", create, destroy, unknown);
    auto* listener_class = AIBinder_Class_define("android.gui.IScreenCaptureListener", create, destroy, receive);
    if (!service || !service_class || !listener_class || !AIBinder_associateClass(service, service_class)) return 5;
    AIBinder* listener = AIBinder_new(listener_class, nullptr);
    if (!listener) return 6;
    set_threads(1);
    start_threads();
    AParcel* input = nullptr;
    AParcel* output = nullptr;
    int rc = AIBinder_prepareTransaction(service, &input);
    // DisplayCaptureArgs is size-delimited and contains nested CaptureArgs,
    // then displayToken and explicit small output width/height.
    if (rc == STATUS_OK) rc = AParcel_writeInt32(input, 1);
    const int32_t args_start = input ? AParcel_getDataPosition(input) : 0;
    if (rc == STATUS_OK) rc = AParcel_writeInt32(input, 0);
    if (rc == STATUS_OK && !write_capture(input, values[0], values[1], values[2], values[3])) rc = STATUS_BAD_VALUE;
    if (rc == STATUS_OK) rc = AParcel_writeStrongBinder(input, display_token);
    if (rc == STATUS_OK) rc = AParcel_writeInt32(input, values[2] - values[0]);
    if (rc == STATUS_OK) rc = AParcel_writeInt32(input, values[3] - values[1]);
    const int32_t args_end = input ? AParcel_getDataPosition(input) : 0;
    if (rc == STATUS_OK) rc = AParcel_setDataPosition(input, args_start);
    if (rc == STATUS_OK) rc = AParcel_writeInt32(input, args_end - args_start);
    if (rc == STATUS_OK) rc = AParcel_setDataPosition(input, args_end);
    if (rc == STATUS_OK) rc = AParcel_writeStrongBinder(input, listener);
    // Actual current Vivo captureDisplay Bp code: transaction 26, FLAG_ONEWAY.
    if (rc == STATUS_OK) rc = AIBinder_transact(service, 26, &input, &output, FLAG_ONEWAY);
    printf("CAPTURE_REQUEST=%d\n", rc);
    if (input) AParcel_delete(input);
    if (output) AParcel_delete(output);
    if (rc != STATUS_OK) return 7;
    timespec deadline{}; clock_gettime(CLOCK_REALTIME, &deadline); deadline.tv_sec += 5;
    pthread_mutex_lock(&mutex);
    while (!completed && pthread_cond_timedwait(&changed, &mutex, &deadline) == 0) {}
    const bool got = completed;
    const int final_result = result_code;
    pthread_mutex_unlock(&mutex);
    printf("FINITE_RESULT completed=%d result=%d\n", got, final_result);
    fflush(stdout);
    // Bound all callback lifetimes to this diagnostic process. No service is registered.
    _Exit(got && final_result == 0 ? 0 : 8);
}
